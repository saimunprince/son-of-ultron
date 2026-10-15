"""Live 2026-10-15, 12:54-15:35, the network was down. Every three minutes the
cycle started a task that failed at its first brain call ("All brains
failed"), counted it as an attempt, blocked objective 237 and four more, and
derived nested "learn how to do what #239 could not" follow-ups from the
outage. A task no brain answered is not an attempt: the objective stays open,
nothing follows from it, and the next cycle waits longer."""

import asyncio

from syrax import autonomy as auto
from syrax.autonomy import Autonomy
from syrax.journal import Journal
from syrax.test_autonomy import FakeCore

OUTAGE = "All brains failed. Google Gemini: unreachable | OpenRouter (free models): unreachable | Groq: request too large"


class OutageCore(FakeCore):
    def __init__(self, journal, tools, error=OUTAGE):
        super().__init__(journal, tools)
        self.error = error

    async def submit(self, goal, said, session_id, kind="conversation", **kw):
        t = self.journal.start_task_sync(said or goal, session_id=session_id, kind=kind)
        self.submitted.append((t, goal, kind))
        self.journal.record_sync("task.failed", {"error": self.error}, task_id=t)
        return t


def setup(tmp_path, error=OUTAGE):
    j = Journal(tmp_path / "j.db")
    core = OutageCore(j, ["terminate"], error)
    a = Autonomy(core, j)
    a.reflect = False
    o = j.add_objective_sync("Memory expiry for inferences", "respecified", 1, "human", {"kind": "change_released"})
    return j, core, a, o


def test_a_task_no_brain_answered_is_not_an_attempt(tmp_path):
    j, core, a, o = setup(tmp_path)
    for _ in range(4):
        rep = asyncio.run(a.run_once(force=True))
        assert rep.outcome == "NO_BRAIN" and rep.task_id
    row = j.objective(o["id"])
    assert row["status"] == "OPEN" and row["attempts"] == 0
    assert any("not an attempt" in str(e["payload"]) for e in j.recent_events() if e["type"] == "objective.updated")
    assert not [x for x in j.objectives(limit=100) if (x["key"] or "").startswith("followup:")]
    assert len(core.submitted) == 4 and all(t[1] for t in core.submitted)


def test_any_other_failure_still_counts(tmp_path):
    j, core, a, o = setup(tmp_path, error="scripted failure")
    rep = asyncio.run(a.run_once(force=True))
    assert rep.outcome == "RAN" and j.objective(o["id"])["attempts"] == 1


def test_the_loop_waits_longer_after_an_outage(tmp_path, monkeypatch):
    j, core, a, o = setup(tmp_path)
    a.set_enabled(True)
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    waits = []

    async def sleep(s):
        waits.append(s)

    monkeypatch.setattr(auto.asyncio, "sleep", sleep)
    asyncio.run(a.loop(max_cycles=1))
    assert waits == [auto.NO_BRAIN_INTERVAL_S]
