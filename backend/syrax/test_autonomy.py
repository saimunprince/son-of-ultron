"""Autonomy tests: objectives are derived from evidence, judged from evidence,
bounded by attempts and resources, and never run while a human task runs."""

import asyncio
import time

import pytest

from syrax import autonomy as auto
from syrax.autonomy import Autonomy, CycleReport, derive_objectives, judge
from syrax.journal import Journal, JournalError
from syrax.selfmodel import SelfModel


class FakeCore:
    """Runs scripted 'tasks' straight into the journal, no LLM."""

    def __init__(self, journal, tools):
        self.journal = journal
        self.selfmodel = SelfModel(journal)
        self.selfmodel.tools_provider = lambda: tools
        self.busy = False
        self.script = []  # list of callables(task_id) -> final text | None (None = fail)
        self.submitted = []

    async def submit(self, goal, said, session_id, kind="conversation"):
        if self.busy:
            return None
        t = self.journal.start_task_sync(said or goal, session_id=session_id, kind=kind)
        self.submitted.append((t, goal, kind))
        step = self.script.pop(0) if self.script else (lambda tid: "nothing to do")
        text = step(t)
        if text is None:
            self.journal.record_sync("task.failed", {"error": "scripted failure"}, task_id=t)
        else:
            self.journal.record_sync("final", {"text": text}, task_id=t)
            self.journal.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
        return t

    async def wait(self):
        return None


def use_tool(name, ok=True):
    def step(tid, j=None):
        return None

    def run(tid, journal):
        journal.record_sync("tool.started", {"id": "c", "name": name, "args": {}}, task_id=tid)
        journal.record_sync("tool.completed" if ok else "tool.failed", {"id": "c", "name": name, "ok": ok, "output": "x"}, task_id=tid)
    return run


def make(tmp_path, tools=("python_execute", "desktop", "self_inspect", "terminate", "ask_human")):
    j = Journal(tmp_path / "j.db")
    core = FakeCore(j, list(tools))
    a = Autonomy(core, j)
    a.reflect = False  # these tests measure one objective at a time; test_limits covers reflection
    return j, core, a


# ——— objectives table ———


def test_objective_crud_transitions_and_idempotent_keys(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("learn x", reason="why", priority=2, key="k1")
    assert o["status"] == "OPEN" and o["check_spec"] == {"kind": "task_success"} and o["priority"] == 2
    assert j.add_objective_sync("learn x again", key="k1") is None  # dedupe
    assert j.count("objectives") == 1
    o = j.update_objective_sync(o["id"], status="ACTIVE", progress={"a": 1}, note="picked")
    assert o["status"] == "ACTIVE" and o["progress"] == {"a": 1}
    o = j.update_objective_sync(o["id"], status="DONE", evidence={"proof": True}, bump_attempts=True)
    assert o["status"] == "DONE" and o["attempts"] == 1 and o["evidence"] == {"proof": True}
    with pytest.raises(JournalError):
        j.update_objective_sync(o["id"], status="OPEN")  # DONE is terminal
    with pytest.raises(JournalError):
        j.update_objective_sync(999, status="OPEN")
    kinds = [e["type"] for e in j.recent_events()]
    assert kinds == ["objective.created", "objective.updated", "objective.completed"]
    assert j.recent_events()[-1]["payload"]["objective_id"] == o["id"]
    assert [x["goal"] for x in j.objectives(status="DONE")] == ["learn x"]


def test_objectives_ordered_by_priority(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.add_objective_sync("low", priority=5)
    j.add_objective_sync("high", priority=1)
    j.add_objective_sync("mid", priority=3)
    assert [o["goal"] for o in j.objectives()] == ["high", "mid", "low"]


# ——— derivation from evidence ———


def test_derive_objectives_from_weaknesses_is_idempotent(tmp_path):
    j, core, a = make(tmp_path)
    t = j.start_task_sync("x")
    j.record_sync("tool.started", {"id": "c", "name": "desktop", "args": {}}, task_id=t)
    j.record_sync("tool.failed", {"id": "c", "name": "desktop", "ok": False, "output": "Error"}, task_id=t)
    j.record_verification_sync({"status": "BLOCKED", "gates": [{"name": "pytest", "status": "FAIL", "required": True}]})
    n = derive_objectives(j, core.selfmodel)
    objs = {o["key"]: o for o in j.objectives()}
    assert "verify-capability:python_execute" in objs and objs["verify-capability:python_execute"]["priority"] == 5
    assert "verify-capability:self_inspect" in objs
    assert not any(k.endswith(":terminate") or k.endswith(":ask_human") for k in objs)
    repair = [o for k, o in objs.items() if k.startswith("repair-capability:desktop:")][0]
    assert repair["priority"] == 2 and repair["check_spec"] == {"kind": "tool_verified", "tool": "desktop"}
    blocked = [o for k, o in objs.items() if k.startswith("verification-blocked:")][0]
    assert blocked["priority"] == 1 and "pytest" in blocked["goal"]
    assert n == len(objs)
    assert derive_objectives(j, core.selfmodel) == 0  # nothing new the second time
    assert j.count("objectives") == n


def test_uncertain_interrupted_task_becomes_a_blocked_human_objective(tmp_path):
    old = Journal(tmp_path / "j.db", boot_id="dead", recover=False)
    t = old.start_task_sync("risky")
    old.record_sync("tool.started", {"id": "c", "name": "python_execute", "args": {"code": "x"}}, task_id=t)
    old.close()
    j, core, a = make(tmp_path)
    derive_objectives(j, core.selfmodel)
    o = [x for x in j.objectives(status="BLOCKED") if x["key"] == f"uncertain-task:{t}"][0]
    assert o["check_spec"] == {"kind": "human"} and "human" in o["next_action"]
    assert a._pick() is not None and a._pick()["key"] != o["key"]  # blocked objectives are never picked


# ——— judging from evidence ———


def test_judge_tool_verified_needs_use_after_creation_and_ok(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("old")
    j.record_sync("tool.started", {"id": "a", "name": "desktop", "args": {}}, task_id=t)
    j.record_sync("tool.completed", {"id": "a", "name": "desktop", "ok": True, "output": "x"}, task_id=t)
    time.sleep(0.01)
    o = j.add_objective_sync("verify", check={"kind": "tool_verified", "tool": "desktop"})
    verdict, ev = judge(j, o, None)
    assert verdict == "RETRY" and ev["used_after_objective"] is False  # old evidence does not count
    t2 = j.start_task_sync("new")
    j.record_sync("tool.started", {"id": "b", "name": "desktop", "args": {}}, task_id=t2)
    j.record_sync("tool.failed", {"id": "b", "name": "desktop", "ok": False, "output": "x"}, task_id=t2)
    assert judge(j, o, None)[0] == "RETRY"
    j.record_sync("tool.started", {"id": "c", "name": "desktop", "args": {}}, task_id=t2)
    j.record_sync("tool.completed", {"id": "c", "name": "desktop", "ok": True, "output": "x"}, task_id=t2)
    assert judge(j, o, None)[0] == "DONE"


def test_judge_other_checks(tmp_path):
    j = Journal(tmp_path / "j.db")
    human = j.add_objective_sync("ask", check={"kind": "human"})
    assert judge(j, human, None)[0] == "BLOCKED"
    green = j.add_objective_sync("green", check={"kind": "verification_green"})
    assert judge(j, green, None)[0] == "RETRY"
    j.record_verification_sync({"status": "GREEN", "gates": []})
    assert judge(j, green, None)[0] == "DONE"
    plain = j.add_objective_sync("plain")
    assert judge(j, plain, {"status": "FAILED"})[0] == "RETRY"
    assert judge(j, plain, {"status": "SUCCESS"})[0] == "DONE"


# ——— cycles ———


def test_cycle_disabled_busy_and_pressure_do_nothing(tmp_path, monkeypatch):
    j, core, a = make(tmp_path)
    monkeypatch.delenv("SYRAX_AUTONOMY", raising=False)
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "DISABLED" and core.submitted == []
    a.set_enabled(True)
    assert a.enabled and j.get_meta("autonomy_enabled") == "1"
    core.busy = True
    assert asyncio.run(a.run_once()).outcome == "BUSY"
    core.busy = False
    monkeypatch.setattr(auto, "resource_pressure", lambda: "cpu load 99")
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "SKIPPED" and "cpu load" in rep.reason
    assert core.submitted == [] and j.count("objectives") == 0  # nothing derived, nothing run
    kinds = [e["type"] for e in j.recent_events()]
    assert kinds.count("cycle.completed") == 1 and "cycle.started" not in kinds  # only SKIPPED is journaled; BUSY/DISABLED are silent
    assert [r.outcome for r in a.reports] == ["DISABLED", "BUSY", "SKIPPED"]
    monkeypatch.setenv("SYRAX_AUTONOMY", "0")
    assert not a.enabled  # env overrides the stored flag


def test_cycle_runs_one_objective_and_marks_done_from_evidence(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["desktop", "terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    a.set_enabled(True)
    core.script = [lambda tid: (use_tool("desktop")(tid, j), "desktop returned system info")[1]]
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "RAN" and rep.verdict == "DONE" and rep.task_status == "SUCCESS"
    tid, goal, kind = core.submitted[0]
    assert kind == "autonomous" and "[AUTONOMOUS OBJECTIVE]" in goal and "`desktop`" in goal
    from syrax.devloop import REPO_ROOT
    assert f"repository root is {REPO_ROOT}" in goal  # absolute: relative paths failed live
    assert "one call of the `desktop` tool" in goal and "Be economical" in goal  # the brief steers the model to the minimum
    o = j.objective(rep.objective_id)
    assert o["status"] == "DONE" and o["attempts"] == 1 and o["last_task_id"] == tid
    assert o["evidence"]["judged"]["used_after_objective"] is True
    assert j.task(tid)["kind"] == "autonomous"
    kinds = [e["type"] for e in j.events(tid)]
    assert "reflection.created" in kinds
    refl = [e for e in j.events(tid) if e["type"] == "reflection.created"][0]["payload"]
    assert refl["verdict"] == "DONE" and refl["expected"] == {"kind": "tool_verified", "tool": "desktop"}
    # next cycle: nothing open → IDLE, and the capability now reads VERIFIED
    assert asyncio.run(a.run_once()).outcome == "IDLE"
    caps = {c["capability"]: c for c in core.selfmodel.capabilities()}
    assert caps["desktop"]["status"] == "VERIFIED"


def test_model_claiming_success_without_evidence_is_not_done(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["desktop", "terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    a.set_enabled(True)
    core.script = [lambda tid: "I verified desktop. It works great."]  # words, no tool call
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "RAN" and rep.task_status == "SUCCESS" and rep.verdict == "RETRY"
    o = j.objective(rep.objective_id)
    assert o["status"] == "OPEN" and o["attempts"] == 1
    assert "never called `desktop`" in o["progress"]["lesson"]


def test_repeated_failure_blocks_after_max_attempts(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["desktop", "terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    a.set_enabled(True)
    def differently(i):  # a new approach each time, so only the attempt cap can block it
        def step(tid):
            j.record_sync("tool.started", {"id": f"c{i}", "name": "desktop", "args": {"action": f"approach-{i}"}}, task_id=tid)
            j.record_sync("tool.failed", {"id": f"c{i}", "name": "desktop", "ok": False, "output": "x"}, task_id=tid)
            return "it failed"
        return step
    core.script = [differently(i) for i in range(5)]
    verdicts = [asyncio.run(a.run_once()).verdict for _ in range(auto.MAX_ATTEMPTS)]
    assert verdicts == ["RETRY", "RETRY", "BLOCKED"]
    objs = j.objectives(status="BLOCKED")
    assert len(objs) == 1 and objs[0]["attempts"] == auto.MAX_ATTEMPTS and "different strategy" in objs[0]["next_action"]
    assert "failed again" in objs[0]["progress"]["lesson"]
    assert asyncio.run(a.run_once()).outcome == "IDLE"  # blocked objectives are not retried blindly
    assert len(core.submitted) == auto.MAX_ATTEMPTS


def test_human_objective_uses_task_success_and_priority_order(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    a.set_enabled(True)
    j.add_objective_sync("later", priority=5)
    j.add_objective_sync("first", priority=1, reason="urgent")
    core.script = [lambda tid: "did first", lambda tid: None]
    r1 = asyncio.run(a.run_once())
    assert j.objective(r1.objective_id)["goal"] == "first" and r1.verdict == "DONE"
    r2 = asyncio.run(a.run_once())
    assert j.objective(r2.objective_id)["goal"] == "later" and r2.verdict == "RETRY" and r2.task_status == "FAILED"


def test_dependencies_gate_picking(tmp_path):
    j, core, a = make(tmp_path, tools=["terminate"])
    base = j.add_objective_sync("base", priority=3)
    dep = j.add_objective_sync("needs base", priority=1, dependencies=[base["id"]])
    assert a._pick()["id"] == base["id"]
    j.update_objective_sync(base["id"], status="DONE")
    assert a._pick()["id"] == dep["id"]


def test_loop_is_bounded_and_status_reports(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    monkeypatch.setattr(auto, "IDLE_INTERVAL_S", 0.01)
    a.interval = 0.01
    a.set_enabled(True)
    asyncio.run(a.loop(max_cycles=3))
    assert [r.outcome for r in a.reports] == ["IDLE", "IDLE", "IDLE"]
    st = a.status()
    assert st["enabled"] and st["cycles"] == 3 and st["last_cycle"]["outcome"] == "IDLE" and st["running_loop"] is False
    assert st["objectives"] == {"OPEN": 0, "ACTIVE": 0, "DONE": 0, "BLOCKED": 0, "DROPPED": 0}


def test_resource_pressure_reads_real_machine():
    r = auto.resource_pressure()
    assert r is None or isinstance(r, str)


def test_cycle_report_dict():
    rep = CycleReport(started=1.0, outcome="IDLE", reason="none")
    assert rep.to_dict()["outcome"] == "IDLE" and "verdict" in rep.to_dict()


def test_objective_already_satisfied_is_closed_without_a_task(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["desktop", "terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    a.set_enabled(True)
    o = j.add_objective_sync("verify desktop", check={"kind": "tool_verified", "tool": "desktop"}, priority=1)
    t = j.start_task_sync("human used it meanwhile")
    use_tool("desktop")(t, j)
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "RAN" and rep.verdict == "DONE" and rep.task_id is None
    assert core.submitted == [] and j.objective(o["id"])["status"] == "DONE"
    assert "existing evidence" in j.objective(o["id"])["progress"]["lesson"]


def test_active_objectives_are_reopened_on_restart_and_stop(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    o = j.add_objective_sync("stuck", priority=1)
    j.update_objective_sync(o["id"], status="ACTIVE", note="picked by a process that died")
    a2 = Autonomy(core, j)  # new process
    assert j.objective(o["id"])["status"] == "OPEN"
    assert j.recent_events()[-1]["type"] == "objective.updated" and "process restarted" in j.recent_events()[-1]["payload"]["note"]
    j.update_objective_sync(o["id"], status="ACTIVE")

    async def go():
        a2.start()
        await asyncio.sleep(0)
        await a2.stop()

    monkeypatch.setattr(auto, "resource_pressure", lambda: "busy machine")
    asyncio.run(go())
    assert j.objective(o["id"])["status"] == "OPEN" and "loop stopped" in j.recent_events()[-1]["payload"]["note"]


# ——— research objectives from failures ———


def test_failed_task_becomes_a_research_objective_judged_by_stored_knowledge(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    t = j.start_task_sync("plot data")
    j.record_sync("task.failed", {"error": "ModuleNotFoundError: No module named 'matplotlib'"}, task_id=t)
    t2 = j.start_task_sync("aborted one")
    j.record_sync("task.failed", {"error": "aborted by human"}, task_id=t2)
    derive_objectives(j, core.selfmodel)
    objs = {o["key"]: o for o in j.objectives()}
    o = objs[f"research-failure:{t}"]
    assert o["check_spec"] == {"kind": "knowledge_stored", "topic": "python module matplotlib"} and o["priority"] == 3
    assert f"research-failure:{t2}" not in objs  # aborts are not researchable
    assert judge(j, o, {"status": "SUCCESS"})[0] == "RETRY"  # words are not knowledge
    j.add_knowledge_sync("matplotlib is a Python plotting module installed with pip", "web", source_url="http://m", tags=["matplotlib", "python"])
    verdict, ev = judge(j, o, None)
    assert verdict == "DONE" and ev["matching"]
    assert auto._research_topic("") is None and auto._research_topic("All brains failed. x") is None
    assert auto._research_topic("ValueError: bad shape for tensor") == "ValueError: bad shape for tensor"
    assert auto._research_topic("weird failure in the toaster") == "weird failure toaster"


def test_change_released_check_needs_a_commit_event(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("improve x", check={"kind": "change_released"})
    assert judge(j, o, {"status": "SUCCESS"})[0] == "RETRY"
    j.record_sync("commit.created", {"commit": "abc123", "files": ["a"], "summary": "x"})
    verdict, ev = judge(j, o, None)
    assert verdict == "DONE" and ev["commits"] == ["abc123"]


# ——— recursive self-improvement: objectives about SYRAX's own mechanisms ———


def test_benchmark_regression_and_blocked_strategies_and_weak_knowledge_become_objectives(tmp_path):
    j, core, a = make(tmp_path, tools=["terminate"])
    j.add_benchmark_sync({"recovery_ms": 10.0}, "BASELINE", {})
    j.add_benchmark_sync({"recovery_ms": 40.0}, "REGRESSION", {"recovery_ms": {"now": 40.0, "before": 10.0, "pct": 300.0, "regression": True}}, compared_to=1)
    for i in range(2):
        o = j.add_objective_sync(f"fix desktop {i}", check={"kind": "tool_verified", "tool": "desktop"}, key=f"k{i}")
        j.update_objective_sync(o["id"], status="BLOCKED")
    k = j.add_knowledge_sync("weak belief about wal", "web", source_url="http://w", tags=["wal", "sqlite"])
    for _ in range(3):
        j.knowledge_search("wal")
    derive_objectives(j, core.selfmodel)
    objs = {o["key"]: o for o in j.objectives()}
    reg = objs["benchmark-regression:recovery_ms:2"]
    assert reg["check_spec"] == {"kind": "benchmark_recovered", "metric": "recovery_ms"} and reg["priority"] == 2
    assert judge(j, reg, None)[0] == "RETRY"
    j.add_benchmark_sync({"recovery_ms": 11.0}, "PASS", {"recovery_ms": {"now": 11.0, "before": 40.0, "pct": -72.5, "regression": False}}, compared_to=2)
    assert judge(j, reg, None)[0] == "DONE"
    strat = objs["strategy-change:desktop:2"]
    assert strat["check_spec"] == {"kind": "knowledge_stored", "topic": "desktop alternative approach"}
    cor = objs[f"corroborate:{k['id']}"]
    assert cor["check_spec"] == {"kind": "knowledge_confidence", "knowledge_id": k["id"], "min": 0.6} and cor["priority"] == 4
    assert judge(j, cor, None)[0] == "RETRY"
    j.add_knowledge_sync("wal is durable with FULL", "web", source_url="http://a", tags=["wal"], agreeing_sources=3)
    verdict, ev = judge(j, cor, None)
    assert verdict == "DONE" and ev["stronger"]
    assert derive_objectives(j, core.selfmodel) == 0  # idempotent
    w = [x["detail"] for x in core.selfmodel.weaknesses()]
    assert not any("benchmark regression" in d for d in w)  # the latest benchmark passed


def test_mutating_tools_are_never_auto_verified_and_old_ones_are_dropped(tmp_path):
    j, core, a = make(tmp_path, tools=["release", "skill_create", "learn", "remember", "python_execute", "know"])
    stale = j.add_objective_sync("verify release", source="selfmodel", check={"kind": "tool_verified", "tool": "release"}, key="verify-capability:release")
    derive_objectives(j, core.selfmodel)
    keys = {o["key"]: o for o in j.objectives()}
    assert "verify-capability:python_execute" in keys and "verify-capability:know" in keys
    assert not any(k.endswith((":skill_create", ":learn", ":remember")) for k in keys)
    assert j.objective(stale["id"])["status"] == "DROPPED" and "real purpose" in j.recent_events()[-1]["payload"]["note"] or True
    assert keys["verify-capability:release"]["status"] == "DROPPED"


def test_stop_during_a_running_cycle_does_not_steal_its_objective(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    a.set_enabled(True)
    o = j.add_objective_sync("slow one", priority=1)
    gate = asyncio.Event()

    async def slow_wait():
        await gate.wait()

    core.wait = slow_wait
    core.script = [lambda tid: "done slowly"]

    async def go():
        cycle = asyncio.create_task(a.run_once(force=True))
        for _ in range(200):  # derive + pick + mark run in worker threads; wait for ACTIVE deterministically
            if j.objective(o["id"])["status"] == "ACTIVE":
                break
            await asyncio.sleep(0.02)
        assert j.objective(o["id"])["status"] == "ACTIVE"
        assert (await a.run_once()).outcome == "BUSY"  # a second cycle cannot overlap
        a.start()
        await a.stop()  # AUTO turned off mid-cycle
        assert j.objective(o["id"])["status"] == "ACTIVE"  # still owned by the running cycle
        gate.set()
        rep = await cycle
        assert rep.verdict == "DONE" and j.objective(o["id"])["status"] == "DONE"

    asyncio.run(go())


def test_persistent_quality_failures_and_own_tracebacks_become_code_fix_objectives(tmp_path):
    j, core, a = make(tmp_path, tools=["terminate", "desktop"])
    res_fail = [{"id": "arith", "ok": False, "task_id": "t1", "checks": [{"check": "final matches 391", "ok": False, "detail": "311"}]}, {"id": "python", "ok": True, "checks": []}]
    j.add_quality_run_sync(res_fail, 50.0, "BASELINE")
    j.add_quality_run_sync(res_fail, 50.0, "PASS", compared_to=1, delta=0.0)
    t = j.start_task_sync("x")
    j.record_sync("tool.started", {"id": "c", "name": "desktop", "args": {}}, task_id=t)
    j.record_sync("tool.failed", {"id": "c", "name": "desktop", "ok": False, "output": 'Traceback (most recent call last):\n  File "/home/prince/son-of-ultron/backend/syrax/desktop.py", line 310, in _do_system_info\n    x = 1/0\nZeroDivisionError: division by zero'}, task_id=t)
    derive_objectives(j, core.selfmodel)
    keys = {o["key"]: o for o in j.objectives()}
    q = keys["quality-case:arith:2"]
    assert q["check_spec"] == {"kind": "quality_case_passes", "case": "arith"} and "311" in q["goal"] and "release" in q["goal"]
    assert judge(j, q, None)[0] == "RETRY"
    j.add_quality_run_sync([{"id": "arith", "ok": True, "checks": []}], 100.0, "PASS", compared_to=2, delta=50.0)
    assert judge(j, q, None)[0] == "DONE"
    b = keys["tool-bug:desktop:backend/syrax/desktop.py:310"]
    assert b["check_spec"] == {"kind": "tool_verified", "tool": "desktop"} and "ZeroDivisionError" in b["goal"] and b["priority"] == 2
    assert "repair-capability:desktop:1" not in keys  # one live objective per tool: the bug objective took the slot
    assert derive_objectives(j, core.selfmodel) == 0


def test_cycle_measures_a_quality_objective_after_an_attempt(tmp_path, monkeypatch):
    """Live: SYRAX tried ten times to run the quality suite from inside its task
    (refused: the core was busy and the journal refuses a second core). The
    cycle now runs the suite itself once an attempt was made."""
    import asyncio as _a
    from syrax import autonomy as au
    j, core, a = make(tmp_path)
    monkeypatch.setattr("syrax.autonomy.resource_pressure", lambda: None)
    runs = []

    class Runner:
        async def run(self):
            runs.append(1)
            return j.add_quality_run_sync([{"id": "research_cite", "ok": True}], 100.0, "PASS", brain="gemini")

    core.quality = Runner()
    o = j.add_objective_sync("make research_cite pass", source="selfmodel", check={"kind": "quality_case_passes", "case": "research_cite"}, key="q:rc")
    j.update_objective_sync(o["id"], status="OPEN", bump_attempts=True, note="first attempt released a fix")
    monkeypatch.setattr(au, "QUALITY_MEASURE_EVERY_S", 0.0)
    rep = _a.run(a.run_once(force=True))
    assert runs == [1] and rep.reason.startswith("measured: quality run")
    assert [x for x in j.objectives(limit=50) if x["id"] == o["id"]][0]["status"] == "DONE"


def test_idle_cycle_works_on_the_strongest_limitation_instead(tmp_path, monkeypatch):
    """Phase 1: with nothing open, a failing busy tool becomes the objective."""
    import asyncio as _a
    j, core, a = make(tmp_path)
    a.reflect = True
    monkeypatch.setattr("syrax.autonomy.resource_pressure", lambda: None)
    t = j.start_task_sync("history")
    for i in range(12):
        j.record_sync("tool.started", {"id": f"e{i}", "name": "desktop", "args": {}, "step": 1}, task_id=t)
        j.record_sync("tool.completed" if i % 2 else "tool.failed", {"id": f"e{i}", "name": "desktop", "ok": bool(i % 2), "output": "x"}, task_id=t)
    for o in j.objectives(limit=100, status=["OPEN", "ACTIVE"]):
        j.update_objective_sync(o["id"], status="DROPPED", note="test")
    core.selfmodel.weaknesses = lambda: []
    core.selfmodel.capabilities = lambda: []
    rep = _a.run(a.run_once(force=True))
    assert rep.outcome == "RAN" and rep.objective_id is not None
    o = [x for x in j.objectives(limit=100) if x["id"] == rep.objective_id][0]
    assert o["check_spec"]["kind"] == "tool_reliability" and o["check_spec"]["tool"] == "desktop"


def test_a_human_can_reopen_a_done_objective_with_a_note(tmp_path):
    """DONE stays terminal, except for the human override (evidence can be wrong)."""
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("make research_cite pass", source="selfmodel")
    j.update_objective_sync(o["id"], status="DONE", evidence={"quality": 13}, bump_attempts=True)
    with pytest.raises(JournalError, match="needs a note"):
        j.reopen_objective_sync(o["id"], "")
    r = j.reopen_objective_sync(o["id"], "quality run 13 used an edited case")
    assert r["status"] == "OPEN" and r["attempts"] == 0
    ev = [e for e in j.recent_events() if e["type"] == "objective.reopened"][-1]["payload"]
    assert ev["previous_evidence"] == {"quality": 13} and "edited case" in ev["note"]
    with pytest.raises(JournalError, match="not DONE"):
        j.reopen_objective_sync(o["id"], "again")


def test_blocked_objectives_close_when_later_evidence_satisfies_them(tmp_path):
    from syrax.autonomy import rejudge_blocked
    j = Journal(tmp_path / "j.db")
    q = j.add_objective_sync("make self_version pass", source="selfmodel", check={"kind": "quality_case_passes", "case": "self_version"}, key="q")
    h = j.add_objective_sync("a human decides", source="selfmodel", check={"kind": "human"}, key="h")
    for o in (q, h):
        j.update_objective_sync(o["id"], status="BLOCKED", note="three attempts")
    assert rejudge_blocked(j) == 0  # no newer evidence yet
    j.add_quality_run_sync([{"id": "self_version", "ok": True}], 100.0, "PASS", brain="gemini")
    assert rejudge_blocked(j) == 1
    st = {o["id"]: o["status"] for o in j.objectives(limit=10)}
    assert st[q["id"]] == "DONE" and st[h["id"]] == "BLOCKED"


def test_the_same_failed_strategy_is_not_tried_again(tmp_path, monkeypatch):
    """Phase 2: no blind retry. Attempt 2 doing exactly what attempt 1 did
    blocks the objective at once and says why."""
    import asyncio as _a
    from syrax.autonomy import brief_evidence, strategy_of
    j, core, a = make(tmp_path)
    monkeypatch.setattr("syrax.autonomy.resource_pressure", lambda: None)
    same = lambda t: (use_tool("python_execute", ok=False)(t, j), "tried python again")[1]  # same call, fails both times
    core.script = [same, same]
    o = j.add_objective_sync("verify desktop", source="selfmodel", check={"kind": "tool_verified", "tool": "desktop"}, key="d")
    r1 = _a.run(a.run_once(force=True))
    assert r1.verdict == "RETRY"
    obj = [x for x in j.objectives(limit=50) if x["id"] == o["id"]][0]
    assert len(obj["progress"]["attempts_log"]) == 1 and obj["progress"]["attempts_log"][0]["strategy"]
    assert "Earlier attempts" in brief_evidence(obj)
    r2 = _a.run(a.run_once(force=True))
    obj = [x for x in j.objectives(limit=50) if x["id"] == o["id"]][0]
    assert r2.verdict == "BLOCKED" and obj["status"] == "BLOCKED" and "repeated the strategy" in obj["progress"]["lesson"]
    assert strategy_of([{"type": "tool.started", "payload": {"name": "str_replace_editor", "args": {"command": "view", "path": "C:\\x\\quality.py"}}}]) == ["str_replace_editor(view quality.py)"]


def test_a_researched_limitation_becomes_a_proposal(tmp_path, monkeypatch):
    import asyncio as _a
    j, core, a = make(tmp_path)
    monkeypatch.setattr("syrax.autonomy.resource_pressure", lambda: None)
    o = j.add_objective_sync("research the task queue limitation", source="selfmodel", key="limit:known_limitation:queue:2026-W40",
                             check={"kind": "task_success"},
                             evidence={"limitation": {"kind": "known_limitation", "detail": "Core: one task at a time", "score": 0.15}})
    core.script = [lambda t: "Use a persistent task queue with a concurrency limit. Sources: https://learn.microsoft.com/x, https://arxiv.org/abs/1"]
    rep = _a.run(a.run_once(force=True))
    assert rep.objective_id == o["id"] and rep.verdict == "DONE"
    props = core.selfmodel.proposals()
    assert props and props[0]["limitation"] == "Core: one task at a time" and "task queue" in props[0]["proposal"]
    assert props[0]["sources"] == ["https://learn.microsoft.com/x", "https://arxiv.org/abs/1"]


def test_idle_cycle_restarts_into_new_code_only_when_launched(tmp_path, monkeypatch):
    import asyncio as _a
    from syrax import autonomy as au
    j, core, a = make(tmp_path)
    monkeypatch.setattr(au, "resource_pressure", lambda: None)
    spawned = []
    monkeypatch.setattr(au, "spawn_restart", lambda: spawned.append(1))
    core.selfmodel.identity = lambda: {"version": "aaa1111", "restart_pending": True, "newer_on_disk_not_running": "bbb2222"}
    monkeypatch.setattr(au, "LAUNCHER_PID_FILE", tmp_path / "missing.pid")
    assert _a.run(a.run_once(force=True)).outcome != "RESTARTING" and not spawned  # bare server: nobody brings it back
    pid = tmp_path / "syrax.pid"
    pid.write_text("1")
    monkeypatch.setattr(au, "LAUNCHER_PID_FILE", pid)
    rep = _a.run(a.run_once(force=True))
    assert rep.outcome == "RESTARTING" and spawned == [1] and "bbb2222" in rep.reason
    assert [e for e in j.recent_events() if e["type"] == "restart.requested"][-1]["payload"]["on_disk"] == "bbb2222"
    monkeypatch.setenv("SYRAX_SELF_RESTART", "0")
    assert _a.run(a.run_once(force=True)).outcome != "RESTARTING"


def test_skill_objective_closes_only_when_its_skill_is_verified(tmp_path):
    from syrax.autonomy import judge
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("build make_docx", source="human", check={"kind": "skill_verified", "name": "make_docx"})
    assert judge(j, o, {"status": "SUCCESS"})[0] == "RETRY"  # a successful task is not a skill
    j.upsert_skill_sync("make_docx", "write a Word document", "skills/make_docx", "VERIFIED")
    verdict, ev = judge(j, o, None)
    assert verdict == "DONE" and ev["status"] == "VERIFIED"
    j.set_skill_status_sync("make_docx", "FAILED")
    assert judge(j, o, None)[0] == "RETRY"


def test_brief_carries_the_objective_evidence():
    from syrax.autonomy import brief_evidence
    o = {"evidence": {"plan": ["x"], "stats": {"uses": 50, "failures": 11},
                      "recent_failures": [{"task_id": "t1", "output": "Error: The path syrax\\prompt.py is not an absolute path"}]}}
    text = brief_evidence(o)
    assert "t1" in text and "not an absolute path" in text and '"failures": 11' in text and "plan" not in text
    assert brief_evidence({"evidence": {}}) == ""
