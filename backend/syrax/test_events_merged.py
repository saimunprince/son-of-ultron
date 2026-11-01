"""Audit 2026-11-01 (lifecycle LIFE-6): journal.events(task_id) filtered id > 0 by default, so a task merged in from
the Windows journal (ids below zero) showed no events in the WHY view, follow-ups and plans. All of a task's events are
returned unless after_id is given."""

import json
import time

from syrax.journal import Journal


def test_a_merged_tasks_events_are_returned(tmp_path):
    j = Journal(tmp_path / "j.db")
    now = time.time()
    j._db.execute("INSERT INTO tasks (task_id, goal, kind, status, created, updated, boot_id) "
                  "VALUES ('win1','old','conversation','SUCCESS',?,?,'windows-import')", (now, now))
    for i, typ in enumerate(["task.started", "final"]):
        j._db.execute("INSERT INTO events (id, ts, task_id, type, payload, seq) VALUES (?, ?, 'win1', ?, ?, ?)",
                      (-10_000_000 + i, now, typ, json.dumps({"text": "x"}), i + 1))
    assert [e["type"] for e in j.events("win1")] == ["task.started", "final"]
    assert j.events("win1", after_id=0) == []  # an explicit after_id still filters
