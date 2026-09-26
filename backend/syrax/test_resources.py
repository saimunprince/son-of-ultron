"""Resource awareness, quiet hours and journal maintenance."""

import asyncio
import time

from syrax import autonomy as auto
from syrax import resources
from syrax.autonomy import Autonomy
from syrax.journal import Journal


def test_snapshot_measures_the_machine():
    s = resources.snapshot()
    assert s["cpu"]["cores"] >= 1 and s["memory_mb"]["total_mb"] > 0 and s["disk"]["free_gb"] >= 0
    assert s["battery"] is None or {"percent", "status", "discharging"} <= set(s["battery"])
    assert s["quiet_hours"] == {"window": None, "active": False} or s["quiet_hours"]["window"]


def base():
    return {
        "cpu": {"cores": 4, "load_1_5_15": [1.0, 1.0, 1.0], "load_per_core": 0.25},
        "memory_mb": {"total_mb": 16000, "available_mb": 8000},
        "disk": {"free_gb": 50.0, "total_gb": 200.0},
        "battery": None,
        "quiet_hours": {"window": None, "active": False},
    }


def test_pressure_thresholds():
    assert resources.pressure(base()) is None
    s = base(); s["cpu"]["load_per_core"] = 2.0; s["cpu"]["load_1_5_15"] = [8.0, 1, 1]
    assert "cpu load 8.0" in resources.pressure(s)
    s = base(); s["memory_mb"]["available_mb"] = 500
    assert "500 MB RAM" in resources.pressure(s)
    s = base(); s["disk"]["free_gb"] = 1.5
    assert "1.5 GB disk" in resources.pressure(s)
    s = base(); s["battery"] = {"percent": 20, "status": "Discharging", "discharging": True}
    assert "battery at 20%" in resources.pressure(s)
    s = base(); s["battery"] = {"percent": 20, "status": "Charging", "discharging": False}
    assert resources.pressure(s) is None
    s = base(); s["quiet_hours"] = {"window": (23, 7), "active": True}
    assert resources.pressure(s) == "quiet hours 23:00-07:00"
    s = base(); s["cpu"]["load_per_core"] = None; s["memory_mb"]["available_mb"] = None; s["disk"] = None
    assert resources.pressure(s) is None  # unmeasurable is not pressure


def test_quiet_hours_parsing_and_wraparound(monkeypatch):
    monkeypatch.delenv("SYRAX_QUIET_HOURS", raising=False)
    assert resources.quiet_hours() is None and not resources.in_quiet_hours(3)
    monkeypatch.setenv("SYRAX_QUIET_HOURS", "23-7")
    assert resources.quiet_hours() == (23, 7)
    assert resources.in_quiet_hours(23) and resources.in_quiet_hours(2) and not resources.in_quiet_hours(7) and not resources.in_quiet_hours(12)
    monkeypatch.setenv("SYRAX_QUIET_HOURS", "9-17")
    assert resources.in_quiet_hours(9) and resources.in_quiet_hours(16) and not resources.in_quiet_hours(17) and not resources.in_quiet_hours(3)
    for bad in ("nope", "25-3", "5-5", "5"):
        monkeypatch.setenv("SYRAX_QUIET_HOURS", bad)
        assert resources.quiet_hours() is None


def seed(j: Journal, age_days: float, status="SUCCESS"):
    t = j.start_task_sync(f"task {age_days}d")
    for i in range(3):
        j.record_sync("think", {"step": i + 1, "content": "x" * 50}, task_id=t)
    j.record_sync("brain.answered", {"provider": "p", "label": "P", "model": "m"}, task_id=t)
    j.record_sync("tool.started", {"id": "c", "name": "python_execute", "args": {}}, task_id=t)
    j.record_sync("tool.completed", {"id": "c", "name": "python_execute", "ok": True, "output": "1"}, task_id=t)
    j.checkpoint_sync(t, "observed:python_execute", context=[{"role": "user", "content": "hello"}])
    if status == "SUCCESS":
        j.record_sync("final", {"text": "done"}, task_id=t)
        j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    old = time.time() - age_days * 86400
    with j._txn() as cur:
        cur.execute("UPDATE tasks SET updated=? WHERE task_id=?", (old, t))
    return t


def test_maintenance_prunes_only_old_finished_tasks_and_keeps_the_record(tmp_path):
    j = Journal(tmp_path / "j.db")
    old = seed(j, 45)
    fresh = seed(j, 2)
    active = seed(j, 45, status="IN_PROGRESS")
    assert j.maintenance_due()
    m = j.maintain(retain_days=30)
    assert m["tasks_examined"] == 1 and m["events_pruned"] == 4 and m["checkpoint_contexts_trimmed"] == 1
    kinds = [e["type"] for e in j.events(old)]
    assert "think" not in kinds and "brain.answered" not in kinds
    assert kinds == ["task.started", "tool.started", "tool.completed", "checkpoint.created", "final", "task.completed"]
    assert j.latest_checkpoint(old)["context"] == [] and j.task(old)["status"] == "SUCCESS"
    assert [e["type"] for e in j.events(fresh)].count("think") == 3 and j.latest_checkpoint(fresh)["context"]
    assert [e["type"] for e in j.events(active)].count("think") == 3  # still running: untouched
    assert j.recent_events()[-1]["type"] == "maintenance.completed"
    assert not j.maintenance_due(every_s=86400)
    assert j.maintenance_due(every_s=0)
    again = j.maintain(retain_days=30)
    assert again["events_pruned"] == 0 and again["checkpoint_contexts_trimmed"] == 0  # idempotent
    assert m["wal_checkpoint"] is not None and m["bytes_after"] is not None


class IdleCore:
    def __init__(self, journal):
        self.journal = journal
        self.busy = False

        class SM:
            def capabilities(self):
                return []

            def behavior(self):
                return {"verifications": {"last": None}, "interrupted": [], "recent_failures": []}

        self.selfmodel = SM()


def test_idle_cycle_runs_maintenance_when_due_and_quiet_hours_skip(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    seed(j, 45)
    a = Autonomy(IdleCore(j), j)
    a.set_enabled(True)
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "IDLE" and "maintenance: pruned 4 events" in rep.reason
    assert j.get_meta("last_maintenance") is not None
    rep2 = asyncio.run(a.run_once())
    assert rep2.outcome == "IDLE" and rep2.reason == "no open objective"  # not due again
    st = a.status()
    assert st["resources"]["cpu"]["cores"] >= 1 and "pressure" in st and st["last_maintenance"]
    monkeypatch.setattr(auto, "resource_pressure", resources.pressure)
    monkeypatch.setenv("SYRAX_QUIET_HOURS", f"{time.localtime().tm_hour}-{(time.localtime().tm_hour + 1) % 24}")
    rep3 = asyncio.run(a.run_once())
    assert rep3.outcome == "SKIPPED" and rep3.reason.startswith("quiet hours")
    rep4 = asyncio.run(a.run_once(force=True))
    assert rep4.outcome == "IDLE"  # a human's cycle_now ignores quiet hours
