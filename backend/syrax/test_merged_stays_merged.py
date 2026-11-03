"""Audit 2026-11-01 (LIFE-7): a task merged in from the Windows journal is told from this PC's own by its negative
last_event_id. Any later terminal-OK event on it (a reflection, a skill verdict) set that id to the new positive one,
and the task turned "own": counted in the daily budget and in RISE. A merged task's id stays negative."""

from syrax.journal import Journal


def test_a_merged_task_stays_merged_after_a_late_event(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("old windows work", kind="autonomous")
    j.record_sync("final", {"text": "done"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS", "result": "done"}, task_id=t)
    since = j.task(t)["created"] - 1
    with j._lock:  # what the import script leaves: ids shifted below zero
        j._db.execute("UPDATE tasks SET last_event_id=-5 WHERE task_id=?", (t,))
        j._db.commit()
    assert j.own_tasks_since(since) == 0
    j.record_sync("reflection.created", {"lesson": "x"}, task_id=t)
    assert j.own_tasks_since(since) == 0
    assert j.task(t)["last_event_id"] == -5


def test_an_own_task_still_moves_its_last_event(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("own work", kind="autonomous")
    first = j.task(t)["last_event_id"]
    j.record_sync("final", {"text": "done"}, task_id=t)
    assert j.task(t)["last_event_id"] > first and j.own_tasks_since(0) == 1
