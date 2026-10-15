"""Live 2026-10-15, quality run #44: the autonomy cycle started an objective
task just as a 4-case rerun began; every case found the core busy and the run
was recorded as 0 % REGRESSION, compared with the 51-case run's 92 %. A busy
core is waited for; a run is compared with the latest run that measured the
same cases, on those cases only; and the cycle yields to a run that started
while it built its brief."""

import asyncio

from syrax import quality
from syrax.autonomy import Autonomy
from syrax.journal import Journal
from syrax.quality import QualityRunner
from syrax.test_autonomy import FakeCore as CycleCore

CASE = [{"id": "arith", "prompt": "17*23?", "checks": [{"kind": "final_regex", "pattern": r"\b391\b"}]}]


class Core:
    def __init__(self, j, busy_for=0):
        self.journal, self.busy, self.agent, self.busy_for = j, False, None, busy_for

    async def submit(self, goal, said, session_id, kind="conversation"):
        if self.busy_for > 0:
            self.busy_for -= 1
            return None
        t = self.journal.start_task_sync(said or goal, kind=kind)
        self.journal.record_sync("final", {"text": "391"}, task_id=t)
        self.journal.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
        return t

    async def wait(self):
        return None


def test_a_busy_core_is_waited_for_not_failed(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    naps = []

    async def nap(s):
        naps.append(s)

    monkeypatch.setattr(quality.asyncio, "sleep", nap)
    row = asyncio.run(QualityRunner(Core(j, busy_for=3), j, workspace=tmp_path / "ws")._run(None, CASE, None))
    assert row["pass_rate"] == 100.0 and row["results"][0]["ok"] and len(naps) == 3


def test_a_subset_is_compared_with_the_same_cases(tmp_path):
    j = Journal(tmp_path / "j.db")
    full = [{"id": f"c{i}", "ok": i != 0, "checks": []} for i in range(10)]
    j.add_quality_run_sync(full, 90.0, "BASELINE")
    runner = QualityRunner(Core(j), j, workspace=tmp_path / "ws")
    failing_again = [{"id": "c0", "prompt": "17*23?", "checks": [{"kind": "final_regex", "pattern": r"\b999\b"}]}]
    row = asyncio.run(runner._run(None, failing_again, None))
    assert (row["pass_rate"], row["status"], row["delta"]) == (0.0, "PASS", 0.0)  # it failed before too: no regression
    fixed = [{"id": "c0", "prompt": "17*23?", "checks": [{"kind": "final_regex", "pattern": r"\b391\b"}]}]
    row = asyncio.run(runner._run(None, fixed, None))
    assert (row["pass_rate"], row["status"], row["delta"]) == (100.0, "PASS", 100.0)
    new_case = [{"id": "fresh", "prompt": "17*23?", "checks": [{"kind": "final_regex", "pattern": r"\b391\b"}]}]
    assert asyncio.run(runner._run(None, new_case, None))["status"] == "BASELINE"  # nothing measured it before


def test_the_cycle_yields_to_a_quality_run_that_started_while_it_built_the_brief(tmp_path):
    j = Journal(tmp_path / "j.db")
    core = CycleCore(j, ["terminate"])

    class Q:
        running = False

    core.quality = Q()
    a = Autonomy(core, j)
    a.reflect = False
    o = j.add_objective_sync("change something", "test", 1, "human", {"kind": "change_released"})
    real = a.journal.update_objective

    async def picked(oid, **kw):  # the run begins right after the cycle marks its objective ACTIVE
        out = await real(oid, **kw)
        if kw.get("status") == "ACTIVE":
            core.quality.running = True
        return out

    a.journal.update_objective = picked
    rep = asyncio.run(a.run_once(force=True))
    assert rep.outcome == "BUSY" and not core.submitted and j.objective(o["id"])["status"] == "OPEN"
