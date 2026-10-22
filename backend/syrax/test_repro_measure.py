"""Brief Factory phase 3 (2026-10-22): SYRAX measures itself every day. None of the 57 quality runs up to 2026-10-19
was started by SYRAX, so a failure was seen only when a human ran the suite: hunts would starve and a landed fix
would never be measured again. When the service hunts and the last run is older than a day, the idle cycle runs
the last run's failures (a second same failure is a hunt signal; a pass closes the loop) and a daily slice of the
rest."""

import asyncio
import time

from syrax import autonomy as auto
from syrax import limits, repro
from syrax.test_autonomy import make

IDS = [f"case{i:02d}" for i in range(25)]


def test_a_day_without_a_run_is_due(tmp_path):
    j, core, a = make(tmp_path, tools=["terminate"])
    assert repro.measure_due(j)
    j.add_quality_run_sync([{"id": "case01", "ok": True}], 100.0, "BASELINE")
    assert not repro.measure_due(j) and repro.measure_due(j, now=time.time() + repro.MEASURE_EVERY_S + 60)


def test_the_last_failures_come_first_and_the_rest_rotates_daily(tmp_path):
    j, core, a = make(tmp_path, tools=["terminate"])
    j.add_quality_run_sync([{"id": "case07", "ok": False}, {"id": "case08", "ok": True}, {"id": "gone", "ok": False}], 50.0, "BASELINE")
    day = 86400 * 20000
    today = repro.measure_subset(j, IDS, now=day)
    assert today[0] == "case07" and "gone" not in today and len(set(today)) == len(today)
    assert repro.MEASURE_SIZE <= len(today) <= repro.MEASURE_SIZE + 1  # the slice, and the failure on top of it
    tomorrow = repro.measure_subset(j, IDS, now=day + 86400)
    assert tomorrow[0] == "case07" and set(tomorrow[1:]) != set(today[1:])
    week = set()
    for d in range(3):
        week |= set(repro.measure_subset(j, IDS, now=day + d * 86400))
    assert week == set(IDS)  # every case is measured within a few days


class Runner:
    def __init__(self):
        self.runs = []
        self.running = False

    async def run(self, only=None, cases=None, brain=None):
        self.runs.append(only)
        return {"id": 1, "pass_rate": 100.0}


def test_the_idle_cycle_measures_only_when_the_service_hunts(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    monkeypatch.setattr(limits, "choose", lambda journal, selfmodel: None)
    monkeypatch.setenv("SYRAX_RADAR", "0")
    j, core, a = make(tmp_path, tools=["terminate"])
    core.quality = Runner()
    a.reflect = True
    a.set_enabled(True)
    monkeypatch.setenv("SYRAX_REPRO", "0")
    rep = asyncio.run(a.run_once())
    assert core.quality.runs == [] and rep.outcome == "IDLE"
    monkeypatch.setenv("SYRAX_REPRO", "1")
    rep = asyncio.run(a.run_once())
    assert len(core.quality.runs) == 1 and len(core.quality.runs[0]) == repro.MEASURE_SIZE
    assert rep.outcome == "RAN" and rep.reason.startswith("self-measurement")
