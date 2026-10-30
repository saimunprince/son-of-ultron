"""EVOLUTION_PLAN wave 2 (directions 265 drift detection, 297 value-drift monitoring): rise.py compared one week with
the one before, and nothing raised a slow decline in between. rise.drift reports a metric that got worse in each of
three consecutive days by a material amount, and the autonomy cycle journals it once a day as drift.detected."""

import asyncio

from syrax import autonomy as auto
from syrax import rise
from syrax.journal import Journal
from syrax.test_autonomy import make

NOW = 1_800_000_000.0


def fake(values, unit="%", better="lower"):
    days = {0: values[0], 1: values[1], 2: values[2]}

    def fn(c, t0, t1):
        i = round((t0 - (NOW - 3 * 86400)) / 86400)
        return (days.get(i), "fake")
    return rise.Metric("fake", "Evidence", "fake metric", better, unit, "test", fn)


def run_with(monkeypatch, tmp_path, metric):
    Journal(tmp_path / "j.db").close()
    monkeypatch.setattr(rise, "METRICS", [metric])
    return rise.drift(tmp_path / "j.db", now=NOW)


def test_two_worse_days_in_a_row_by_a_material_amount_is_drift(tmp_path, monkeypatch):
    (d,) = run_with(monkeypatch, tmp_path, fake([10.0, 14.0, 19.0]))
    assert d["metric"] == "fake" and d["values"] == [10.0, 14.0, 19.0]


def test_one_bad_day_a_recovery_or_a_small_change_is_not(tmp_path, monkeypatch):
    assert run_with(monkeypatch, tmp_path, fake([10.0, 10.0, 30.0])) == []  # one step only
    assert run_with(monkeypatch, tmp_path, fake([10.0, 20.0, 15.0])) == []  # recovered
    assert run_with(monkeypatch, tmp_path, fake([10.0, 11.0, 12.0])) == []  # 2 points: not material
    assert run_with(monkeypatch, tmp_path, fake([80.0, 70.0, 60.0], better="higher")) != []  # falling share, higher is better


def test_the_cycle_checks_once_a_day_and_journals_what_it_finds(tmp_path, monkeypatch):
    j, core, a = make(tmp_path)
    monkeypatch.setattr(rise, "drift", lambda path: [{"metric": "unbacked_claims", "values": [0, 2, 5]}])
    asyncio.run(a._check_drift())
    asyncio.run(a._check_drift())  # the same day: not again
    found = [e["payload"] for e in j.recent_events(50) if e["type"] == "drift.detected"]
    assert found == [{"metric": "unbacked_claims", "values": [0, 2, 5]}]
