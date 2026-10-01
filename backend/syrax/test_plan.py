"""Phase 1: plan steps are proven from the journal, a retry resumes at the
first unproven step, and an attempt that proves new steps is progress."""

import asyncio

from syrax import plan
from syrax.journal import Journal
from syrax.test_autonomy import make, use_tool

PLAN = ["Read the failures with self_inspect.", "Group them by cause.", "Use python_execute twice."]
CHECKS = [{"kind": "tool_ok", "tools": ["self_inspect", "journal_query"]}, None, {"kind": "tool_ok", "tools": ["python_execute"], "min": 2}]


def test_steps_are_proven_only_by_journal_evidence(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = {"evidence": {"plan": PLAN + ["Release the fix.", "Learn why."], "plan_checks": CHECKS + [{"kind": "released"}, {"kind": "learned"}]}}
    t = j.start_task_sync("x", kind="autonomous")
    use_tool("self_inspect")(t, j)
    use_tool("python_execute", ok=False)(t, j)  # a failed call proves nothing
    use_tool("python_execute")(t, j)
    st = plan.status(j, o, [t])
    assert [s["done"] for s in st] == [True, None, False, False, False]
    assert plan.next_step(st)["step"] == 2 and "(1) DONE" in plan.render(st) and "(2) NEXT" in plan.render(st)
    use_tool("python_execute")(t, j)
    j.record_sync("commit.created", {"commit": "abc1234"}, task_id=t)
    st = plan.status(j, o, [t])
    assert [s["done"] for s in st] == [True, True, True, True, False]  # step 2 has no check: done once a later step is
    assert plan.summary(st) == {"proven": 4, "total": 5, "next": 5, "steps": [{"step": i, "done": i < 5} for i in range(1, 6)]}
    assert plan.status(j, {"evidence": {"plan": ["only text"]}}, [t])[0]["done"] is None  # old objectives: no checks, no claims


def test_a_retry_resumes_at_the_next_step_and_progress_is_not_a_blind_repeat(tmp_path, monkeypatch):
    j, core, a = make(tmp_path)
    monkeypatch.setattr("syrax.autonomy.resource_pressure", lambda: None)

    def attempt(t):
        use_tool("self_inspect")(t, j)
        use_tool("python_execute")(t, j)
        return "did a part"

    core.script = [attempt, attempt, attempt]
    o = j.add_objective_sync("fix python_execute", source="selfmodel", check={"kind": "tool_verified", "tool": "desktop"}, key="p",
                             evidence={"plan": PLAN, "plan_checks": CHECKS})
    r1 = asyncio.run(a.run_once(force=True))
    obj = [x for x in j.objectives(limit=10) if x["id"] == o["id"]][0]
    assert r1.verdict == "RETRY" and obj["next_action"].startswith("step 2:") and obj["progress"]["plan"]["proven"] == 1
    assert "1/3 steps proven" in obj["progress"]["lesson"]

    r2 = asyncio.run(a.run_once(force=True))  # same strategy, but the second python call proves step 3
    brief = core.submitted[1][1]
    assert "(1) DONE: Read the failures" in brief and "(2) NEXT" in brief
    obj = [x for x in j.objectives(limit=10) if x["id"] == o["id"]][0]
    assert r2.verdict == "RETRY" and obj["status"] == "OPEN" and obj["progress"]["plan"]["proven"] == 3
    ev = [e for e in j.recent_events(500) if e["type"] == "plan.progressed"]
    assert [e["payload"]["proven"] for e in ev] == [1, 3]

    r3 = asyncio.run(a.run_once(force=True))  # nothing new proven and the same strategy: blocked
    obj = [x for x in j.objectives(limit=10) if x["id"] == o["id"]][0]
    assert r3.verdict == "BLOCKED" and obj["status"] == "BLOCKED"


def test_every_ranked_limitation_plan_has_a_check_per_doing_step(tmp_path):
    from syrax import limits
    from syrax.test_limits import FakeSelf, use
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work")
    use(j, t, "str_replace_editor", True, 10)
    use(j, t, "str_replace_editor", False, 10)
    for _ in range(12):
        j.record_sync("brain.failover", {"provider": "gemini", "reason": "429"})
    ranked = limits.rank(j, FakeSelf([{"kind": "known_limitation", "detail": "no embeddings", "evidence": "docs"}]))
    assert {r["kind"] for r in ranked} == {"tool_reliability", "brain_availability", "known_limitation"}
    for r in ranked:
        assert len(r["plan_checks"]) == len(r["plan"]) and all(c is None or c["kind"] in plan.STEP_KINDS for c in r["plan_checks"])
    chosen = limits.choose(j, FakeSelf())
    o = [x for x in j.objectives() if x["id"] == chosen["objective_id"]][0]
    assert [s["check"] for s in plan.steps_of(o)] == chosen["plan_checks"]  # stored with the objective
