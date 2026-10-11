"""M2: the code-change benchmark. Every case is solvable and not solved
before the change, grading is by a hidden test and an untouched check, a
brain is credited only with what it answered itself, and release work is
routed by the results. Scratch folders and a fake core; no model."""

import asyncio
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from syrax import autonomy as auto
from syrax import codebench, routing
from syrax import core as core_mod
from syrax.devloop import JUDGES
from syrax.journal import Journal, JournalError
from syrax.test_autonomy import make

FIXES = {
    "fix_word_count": {"textstats.py": "def word_count(text):\n    return len(text.split())\n"},
    "inventory_remove": {"inventory.py": (
        "class Inventory:\n    def __init__(self):\n        self.items = {}\n\n"
        "    def add(self, name, qty):\n        self.items[name] = self.items.get(name, 0) + qty\n\n"
        "    def count(self, name):\n        return self.items.get(name, 0)\n\n"
        "    def remove(self, name, qty):\n        if self.items.get(name, 0) < qty:\n            raise ValueError(name)\n"
        "        self.items[name] -= qty\n        if self.items[name] == 0:\n            del self.items[name]\n")},
    "greeting_setting": {
        "config.py": 'DEFAULTS = {"name": "world", "greeting": "Hello"}\n',
        "greet.py": ("from config import DEFAULTS\n\n\ndef greet(name=None, settings=None):\n"
                     "    word = (settings or {}).get(\"greeting\", DEFAULTS[\"greeting\"])\n"
                     "    return word + \", \" + (name or DEFAULTS[\"name\"]) + \"!\"\n")},
    "rename_with_caller": {
        "shapes.py": "def rect_area(w, h):\n    return w * h\n\n\narea = rect_area\n",
        "report.py": "from shapes import rect_area\n\n\ndef describe(w, h):\n    return f\"area {rect_area(w, h)}\"\n"},
}
CASES = {c["id"]: c for c in codebench.CASES}


def visible_check(root, case):
    return subprocess.run([sys.executable, case["check"]], cwd=root, capture_output=True, text=True).returncode == 0


def apply(root, files):
    for name, text in files.items():
        (root / name).write_bytes(text.encode("utf-8"))


@pytest.mark.parametrize("cid", sorted(CASES))
def test_each_case_fails_before_the_change_and_passes_after_a_correct_one(tmp_path, cid):
    case, root = CASES[cid], tmp_path / cid
    codebench.prepare(case, root)
    digest = codebench._digest(root / case["check"])
    assert not visible_check(root, case)  # the task is not already done
    before = codebench.grade(case, root, digest)
    assert before[0]["ok"] and not before[1]["ok"]
    assert set(FIXES[cid]) <= set(case["files"]) and len(FIXES[cid]) == case["files_to_change"]
    apply(root, FIXES[cid])
    assert visible_check(root, case)
    assert all(c["ok"] for c in codebench.grade(case, root, digest))


def test_the_hidden_test_catches_what_the_visible_check_misses(tmp_path):
    case, root = CASES["fix_word_count"], tmp_path / "w"
    codebench.prepare(case, root)
    digest = codebench._digest(root / case["check"])
    apply(root, {"textstats.py": "def word_count(text):\n    return len([w for w in text.split(' ') if w])\n"})
    assert visible_check(root, case)  # passes the visible check...
    res = codebench.grade(case, root, digest)
    assert res[0]["ok"] and not res[1]["ok"] and "AssertionError" in res[1]["detail"]  # ...but not tabs and newlines


def test_editing_the_visible_check_is_a_fail_even_when_the_code_is_right(tmp_path):
    case, root = CASES["fix_word_count"], tmp_path / "w"
    codebench.prepare(case, root)
    digest = codebench._digest(root / case["check"])
    apply(root, FIXES["fix_word_count"])
    (root / "check.py").write_text('print("OK")\n')
    res = codebench.grade(case, root, digest)
    assert not res[0]["ok"] and res[0]["detail"] == "edited or removed" and res[1]["ok"]


def test_a_hanging_change_is_cut_off(tmp_path, monkeypatch):
    monkeypatch.setattr(codebench, "HIDDEN_TIMEOUT_S", 1.0)
    case, root = CASES["fix_word_count"], tmp_path / "w"
    codebench.prepare(case, root)
    apply(root, {"textstats.py": "while True:\n    pass\n"})
    res = codebench.grade(case, root, codebench._digest(root / case["check"]))
    assert not res[1]["ok"] and "ran over" in res[1]["detail"]


def test_a_leftover_from_an_earlier_run_never_changes_the_task(tmp_path):
    case, root = CASES["fix_word_count"], tmp_path / "w"
    codebench.prepare(case, root)
    apply(root, FIXES["fix_word_count"])
    (root / "notes.txt").write_text("left over")
    codebench.prepare(case, root)
    assert sorted(p.name for p in root.iterdir()) == ["check.py", "textstats.py"] and not visible_check(root, case)


# ——— running brains through a fake core ———


class Health:
    def __init__(self, until=0.0):
        self.until = until


class Router:
    def __init__(self, order, cooling=()):
        self.preferred = None
        self.store = type("S", (), {"order": list(order), "enabled": staticmethod(lambda p: True)})()
        self.health = {p: Health(time.time() + 600 if p in cooling else 0.0) for p in order}


class FakeCore:
    """Does each case the way a brain would: `skill[brain]` says which cases it gets right;
    `failover` names brains whose steps another brain answered."""

    def __init__(self, j, order, skill, failover=None, cooling=(), stop_on=None):
        self.journal, self.busy = j, False
        self.agent = type("A", (), {})()
        self.agent.llm = Router(order, cooling)
        self.skill, self.failover, self.stop_on = skill, failover or {}, stop_on
        self.submitted = []

    async def ensure_agent(self):
        return None

    async def submit(self, goal, said, session_id, kind="conversation", max_steps=None):
        assert kind == "eval" and max_steps == codebench.CASE_STEPS
        root = Path(re.search(r"Work in the folder (.+?) \(a small", goal).group(1))
        cid = root.name
        brain = self.agent.llm.preferred
        answered = self.failover.get(brain, brain)
        self.submitted.append((brain, cid))
        t = self.journal.start_task_sync(said, kind=kind)
        for _ in range(3):
            self.journal.record_sync("brain.answered", {"provider": answered}, task_id=t)
        if cid in self.skill.get(answered, ()):
            apply(root, FIXES[cid])
        if self.stop_on == (brain, cid):
            self.journal.record_sync("task.stop_requested", {"source": "ui"}, task_id=t)
            self.journal.record_sync("task.cancelled", {}, task_id=t)
        else:
            self.journal.record_sync("final", {"text": "done"}, task_id=t)
            self.journal.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
        return t

    async def wait(self):
        return None

    async def cancel(self):
        return False


def test_brains_are_measured_and_compared_on_their_own_answers(tmp_path):
    j = Journal(tmp_path / "j.db")
    core = FakeCore(j, ["alpha", "beta"], skill={"alpha": {"fix_word_count"}, "beta": set(CASES)})
    res = asyncio.run(codebench.run_all(core, ws=tmp_path / "ws"))
    runs = {r["brain"]: r for r in res["runs"]}
    assert (runs["alpha"]["passed"], runs["alpha"]["graded"]) == (1, 4) and runs["beta"]["pass_rate"] == 1.0
    assert core.agent.llm.preferred is None  # the pin never outlives the run
    ev = [e["payload"] for e in j.events_of_type("codebench.completed")]
    assert [p["brain"] for p in ev] == ["alpha", "beta"]
    assert any("hidden test passes" in f for c in ev[0]["cases"] for f in c["failed"])
    (exp,) = j.experiments(limit=5)
    assert exp["verdict"] == "CANDIDATE_BETTER" and exp["metric"] == "pass_rate" and "beta" in exp["hypothesis"]
    assert codebench.summary(res) == "alpha 1/4, beta 4/4"
    assert not codebench.due(j) and float(j.get_meta(codebench.RAN)) > 0


def test_a_brain_that_failed_over_is_not_measured_and_not_credited(tmp_path):
    j = Journal(tmp_path / "j.db")
    core = FakeCore(j, ["alpha", "beta"], skill={"beta": set(CASES)}, failover={"alpha": "beta"})
    res = asyncio.run(codebench.run_all(core, ws=tmp_path / "ws"))
    alpha = res["runs"][0]
    assert alpha["graded"] == 0 and alpha["pass_rate"] is None and len(alpha["not_measured"]) == 4
    assert j.experiments(limit=5)[0]["verdict"] == "INCONCLUSIVE"  # beta's work never counts as alpha's
    assert codebench.table(j) == {"alpha": {"graded": 0, "passed": 0, "pass_rate": None},
                                  "beta": {"graded": 4, "passed": 4, "pass_rate": 1.0}}


def test_a_cooling_brain_is_skipped_and_a_stop_ends_the_whole_run(tmp_path):
    j = Journal(tmp_path / "j.db")
    core = FakeCore(j, ["alpha", "beta", "gamma"], skill={}, cooling=("beta",), stop_on=("alpha", "inventory_remove"))
    res = asyncio.run(codebench.run_all(core, ws=tmp_path / "ws"))
    assert res["stopped"] and [r["brain"] for r in res["runs"]] == ["alpha"]
    assert core.submitted == [("alpha", "fix_word_count"), ("alpha", "inventory_remove")]
    assert res["experiments"] == [] and j.get_meta(codebench.RAN) is None and j.get_meta(codebench.ATTEMPTED)
    core2 = FakeCore(j, ["alpha", "beta"], skill={}, cooling=("beta",))
    res2 = asyncio.run(codebench.run_all(core2, ws=tmp_path / "ws"))
    assert res2["skipped"] == {"beta": "cooling down"} and "beta skipped (cooling down)" in codebench.summary(res2)


def test_a_busy_core_is_refused(tmp_path):
    j = Journal(tmp_path / "j.db")
    core = FakeCore(j, ["alpha"], skill={})
    core.busy = True
    with pytest.raises(JournalError):
        asyncio.run(codebench.run_all(core, ws=tmp_path / "ws"))


def test_due_weekly_after_a_failed_try_a_day_and_only_when_the_human_is_quiet(tmp_path):
    j = Journal(tmp_path / "j.db")
    now = time.time()
    assert codebench.due(j, now)
    t = j.start_task_sync("hi")  # the human just talked
    j.record_sync("final", {"text": "hello"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    assert not codebench.due(j, now) and codebench.due(j, now + codebench.HUMAN_QUIET_S + 5)
    later = now + codebench.HUMAN_QUIET_S + 5
    j.set_meta(codebench.ATTEMPTED, str(later))
    assert not codebench.due(j, later + 3600) and codebench.due(j, later + codebench.RETRY_S + 1)
    j.set_meta(codebench.RAN, str(later))
    assert not codebench.due(j, later + codebench.RETRY_S + 1) and codebench.due(j, later + codebench.EVERY_S + 1)


# ——— routing release work ———


def bench(j, brain, graded, passed):
    j.record_sync("codebench.completed", {"brain": brain, "graded": graded, "passed": passed})


def test_release_work_goes_to_the_brain_that_finishes_code_best(tmp_path):
    j = Journal(tmp_path / "j.db")
    assert routing.preferred_for_code(j, ["alpha", "beta"]) is None  # nothing measured
    bench(j, "alpha", 4, 1)
    bench(j, "beta", 3, 3)
    assert routing.preferred_for_code(j, ["alpha", "beta"]) is None  # beta: too few of its own cases
    bench(j, "beta", 2, 2)
    assert routing.preferred_for_code(j, ["alpha", "beta"]) == "beta"
    assert routing.preferred_for_code(j, ["beta", "alpha"]) is None  # already first
    assert routing.preferred_for_code(j, ["gamma", "beta"]) is None  # the human's first brain is unmeasured
    assert routing.preferred_for_code(j, []) is None


def test_a_small_lead_keeps_the_humans_order(tmp_path):
    j = Journal(tmp_path / "j.db")
    bench(j, "alpha", 8, 5)
    bench(j, "beta", 8, 6)
    assert routing.preferred_for_code(j, ["alpha", "beta"]) is None  # 0.125 < MIN_GAP


def test_only_the_window_counts(tmp_path):
    j = Journal(tmp_path / "j.db")
    bench(j, "alpha", 4, 0)
    bench(j, "beta", 4, 4)
    assert routing.preferred_for_code(j, ["alpha", "beta"]) == "beta"
    assert codebench.table(j, now=time.time() + codebench.WINDOW_S + 60) == {}


def test_a_release_task_is_routed_by_the_benchmark_and_journaled(tmp_path, monkeypatch):
    from syrax.autonomy import RELEASE_MARK

    j = Journal(tmp_path / "j.db")
    bench(j, "alpha", 4, 0)
    bench(j, "beta", 4, 4)
    router = Router(["alpha", "beta"])
    router.routed = None
    monkeypatch.setattr(core_mod, "get_router", lambda: router)
    stub = type("C", (), {"journal": j})()
    t = j.start_task_sync("x", kind="autonomous")
    assert core_mod._is_release(f"fix it. The objective {RELEASE_MARK}.") and not core_mod._is_release("say hi")
    asyncio.run(core_mod.Core._route(stub, "edit the file", t, release=True))
    assert router.routed == "beta"
    ev = [e for e in j.events(t) if e["type"] == "brain.routed"]
    assert ev[-1]["payload"] == {"kind": "code_change", "brain": "beta", "instead_of": "alpha"}
    asyncio.run(core_mod.Core._route(stub, "what is the capital of Japan", t, release=False))
    assert router.routed is None  # other work keeps the quality-based routing


# ——— the cycle and the guard rails ———


def test_the_cycle_runs_the_benchmark_only_when_the_service_asks_and_it_is_due(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    monkeypatch.delenv("SYRAX_PUBLISH_RISE", raising=False)
    a.set_enabled(True)
    calls = []

    async def fake_run_all(c, **kw):
        calls.append(c)
        return {"runs": [{"brain": "alpha", "passed": 2, "graded": 4, "not_measured": []}], "skipped": {}}

    monkeypatch.setattr(codebench, "run_all", fake_run_all)
    monkeypatch.delenv("SYRAX_CODEBENCH", raising=False)
    assert asyncio.run(a.run_once()).outcome == "IDLE" and calls == []
    monkeypatch.setenv("SYRAX_CODEBENCH", "1")
    monkeypatch.setattr(codebench, "due", lambda journal, now=None: False)
    assert asyncio.run(a.run_once()).outcome == "IDLE" and calls == []
    monkeypatch.setattr(codebench, "due", lambda journal, now=None: True)
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "RAN" and rep.reason == "code benchmark: alpha 2/4" and calls == [core]


def test_the_benchmark_is_a_judge_and_its_cases_are_well_formed():
    assert "backend/syrax/codebench.py" in JUDGES
    assert len({c["id"] for c in codebench.CASES}) == len(codebench.CASES) >= 4
    assert {c["files_to_change"] for c in codebench.CASES} == {1, 2}
    for c in codebench.CASES:
        assert c["check"] in c["files"] and c["hidden"].strip() and c["request"].strip()
