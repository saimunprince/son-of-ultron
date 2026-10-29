"""2026-10-29: the Windows journal was merged in as history (its ids shifted below zero,
syrax-tools/import_windows_journal.py). The daily autonomy budget then counted 15 autonomous tasks the Windows PC
ran that day: 55 "spent" on this PC, 40 of them its own. It also counted only among the newest 500 tasks. The budget
now counts this PC's own autonomous tasks since midnight, in the journal itself."""

import asyncio
import time

from syrax import autonomy as auto
from syrax.test_autonomy import make


def _imported(j, n):
    """Tasks as the import leaves them: created today on the other PC, their last event id shifted below zero."""
    for i in range(n):
        t = j.start_task_sync(f"windows work {i}", kind="autonomous")
        j._db.execute("UPDATE tasks SET last_event_id=? WHERE task_id=?", (-10_000_000 + 50 + i, t))


def test_imported_tasks_do_not_spend_this_pc_s_budget(tmp_path, monkeypatch):
    j, core, a = make(tmp_path)
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    monkeypatch.setattr(auto, "DAILY_TASKS", 2)
    a.set_enabled(True)
    _imported(j, 5)
    j.start_task_sync("own work", kind="autonomous")
    assert a.autonomous_today() == 1
    rep = asyncio.run(a.run_once())
    assert rep.outcome != "SKIPPED", rep.reason


def test_the_count_is_not_capped_at_the_newest_500_tasks(tmp_path):
    j, core, a = make(tmp_path)
    for i in range(3):
        j.start_task_sync(f"own {i}", kind="autonomous")
    for i in range(505):  # newer human tasks push the own work out of a newest-500 window
        j.start_task_sync(f"human {i}")
    assert a.autonomous_today() == 3


def test_yesterday_s_work_is_not_today_s(tmp_path):
    j, core, a = make(tmp_path)
    t = j.start_task_sync("yesterday", kind="autonomous")
    j._db.execute("UPDATE tasks SET created=? WHERE task_id=?", (time.time() - 2 * 86400, t))
    assert a.autonomous_today() == 0
