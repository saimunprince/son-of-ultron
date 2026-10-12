"""Spoken system alerts: raised only when a condition holds for several
readings in a row, not again within the cooldown, never in quiet hours, and
journaled so the UI shows and speaks them. Fake readings; no real machine."""

import asyncio

from syrax import alerts, catalog
from syrax.journal import Journal


def snap(ram=4000, disk=50.0, battery=None, load=0.3, cores=8):
    return {"memory_mb": {"available_mb": ram, "total_mb": 16000}, "disk": {"free_gb": disk, "total_gb": 500},
            "battery": battery, "cpu": {"cores": cores, "load_1_5_15": [load * cores, 0, 0], "load_per_core": load}}


def test_a_short_spike_is_not_an_alert_but_a_lasting_one_is_once():
    w = alerts.Watch()
    t = 1000.0
    assert w.check(snap(ram=300), t) == [] and w.check(snap(ram=300), t + 60) == []
    assert w.check(snap(ram=300), t + 120) == [{"kind": "ram", "detail": "only 300 MB of memory free"}]
    assert w.check(snap(ram=300), t + 180) == []  # cooldown
    assert w.check(snap(ram=300), t + 120 + alerts.COOLDOWN_S) == [{"kind": "ram", "detail": "only 300 MB of memory free"}]
    w2 = alerts.Watch()
    w2.check(snap(ram=300), t)
    w2.check(snap(ram=3000), t + 60)  # recovered: the streak starts over
    assert w2.check(snap(ram=300), t + 120) == []


def test_disk_battery_and_cpu():
    w = alerts.Watch()
    assert w.check(snap(disk=1.2), 0) == [{"kind": "disk", "detail": "only 1.2 GB free on the disk"}]
    assert w.check(snap(battery={"percent": 9, "status": "Discharging", "discharging": True}), 0)[0]["kind"] == "battery"
    assert alerts.Watch().check(snap(battery={"percent": 9, "status": "Charging", "discharging": False}), 0) == []
    w3 = alerts.Watch()
    for i in range(4):
        assert w3.check(snap(load=2.5), i * 60) == []
    assert w3.check(snap(load=2.5), 300)[0]["kind"] == "cpu"
    assert alerts.Watch().check({"cpu": None, "memory_mb": None, "disk": None, "battery": None}, 0) == []  # nothing measured


def test_the_loop_journals_alerts_and_stays_silent_in_quiet_hours(tmp_path, monkeypatch):
    from syrax import resources

    j = Journal(tmp_path / "j.db")

    async def run(times):
        task = asyncio.ensure_future(alerts.loop(j, snapshot=lambda: snap(disk=1.0), every=0.01))
        await asyncio.sleep(times)
        task.cancel()

    monkeypatch.setattr(resources, "in_quiet_hours", lambda hour=None: True)
    asyncio.run(run(0.1))
    assert j.events_of_type("alert.raised") == []
    monkeypatch.setattr(resources, "in_quiet_hours", lambda hour=None: False)
    asyncio.run(run(0.1))
    raised = j.events_of_type("alert.raised")
    assert len(raised) == 1 and raised[0]["payload"] == {"kind": "disk", "detail": "only 1.0 GB free on the disk"}


def test_the_catalog_says_have():
    assert catalog.by_id()["system_alerts"].status == catalog.HAVE
