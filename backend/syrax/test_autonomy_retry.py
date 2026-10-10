"""A failed release attempt is not lost: its rolled-back diff reaches the next
attempt's brief, and a release objective gets a bigger step budget than
other autonomous work (live: objective 97 ran out of 20 steps)."""

import asyncio

from syrax import autonomy as auto
from syrax.autonomy import RELEASE_STEPS, Autonomy, rolled_back
from syrax.journal import Journal
from syrax.selfmodel import SelfModel


class BudgetCore:
    def __init__(self, journal):
        self.journal = journal
        self.selfmodel = SelfModel(journal)
        self.selfmodel.tools_provider = lambda: ["str_replace_editor", "release", "terminate"]
        self.busy = False
        self.submitted = []  # (task_id, brief, max_steps)
        self.script = []

    async def submit(self, goal, said, session_id, kind="conversation", max_steps=None):
        t = self.journal.start_task_sync(said or goal, session_id=session_id, kind=kind)
        self.submitted.append((t, goal, max_steps))
        (self.script.pop(0) if self.script else (lambda tid: None))(t)
        return t

    async def wait(self):
        return None


def ran_out_of_steps(journal, snapshot):
    def step(t):
        journal.record_sync("tool.started", {"id": "e1", "name": "str_replace_editor", "args": {"command": "str_replace", "path": "backend/syrax/sysinfo.py"}}, task_id=t)
        journal.record_sync("tool.completed", {"id": "e1", "name": "str_replace_editor", "ok": True, "output": "edited"}, task_id=t)
        journal.record_sync("rollback.created", {"reason": "task ended without a committed release", "restored": ["backend/syrax/sysinfo.py"],
                                                 "removed": ["backend/syrax/test_new.py"], "clean": True, "snapshot": snapshot,
                                                 "files": {"backend/syrax/sysinfo.py": "M", "backend/syrax/test_new.py": "??"}}, task_id=t)
        journal.record_sync("final", {"text": "Done."}, task_id=t)
        journal.record_sync("task.completed", {"status": "PARTIAL"}, task_id=t)
    return step


def test_rolled_back_finds_the_kept_diff():
    ev = [{"type": "tool.started", "payload": {}},
          {"type": "rollback.created", "payload": {"snapshot": "/r/1.patch", "restored": ["b.py"], "removed": ["a.py"]}}]
    assert rolled_back(ev) == {"snapshot": "/r/1.patch", "files": ["a.py", "b.py"]}
    assert rolled_back(ev[:1]) is None


def test_a_release_attempt_that_ran_out_of_steps_hands_its_diff_to_the_next(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    j = Journal(tmp_path / "j.db")
    core = BudgetCore(j)
    a = Autonomy(core, j)
    a.reflect = False
    a.set_enabled(True)
    o = j.add_objective_sync("Fix the GPU probe and release it", None, 1, "human", {"kind": "change_released"})
    snap = str(tmp_path / "rollback" / "1-abc.patch")
    core.script = [ran_out_of_steps(j, snap)]
    rep = asyncio.run(a.run_once())
    assert rep.objective_id == o["id"] and rep.verdict == "RETRY"
    _, brief, budget = core.submitted[0]
    assert budget == RELEASE_STEPS and "creates a commit" in brief
    last = j.objective(o["id"])["progress"]["attempts_log"][-1]
    assert last["kept"] == snap and last["kept_files"] == ["backend/syrax/sysinfo.py", "backend/syrax/test_new.py"]
    assert last["lesson"].startswith("ran out of steps; ")
    asyncio.run(a.run_once())
    _, brief2, budget2 = core.submitted[1]
    assert budget2 == RELEASE_STEPS
    assert snap in brief2 and "re-apply what was right" in brief2


def test_other_autonomous_work_keeps_the_default_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    j = Journal(tmp_path / "j.db")
    core = BudgetCore(j)
    a = Autonomy(core, j)
    a.reflect = False
    a.set_enabled(True)
    j.add_objective_sync("Verify the desktop tool", None, 1, "human", {"kind": "tool_verified", "tool": "terminate"})
    asyncio.run(a.run_once())
    assert core.submitted[0][2] is None
