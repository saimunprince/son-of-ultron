"""2026-10-30, the first drift read: tool failures 5.4 -> 10.5 -> 14.1 %. Two causes, neither a decline of the tools:
the window three days back held only Windows events merged into this journal (rows with ids below zero), and the honesty
check refusing an unsupported `learn` claim, or a flight search for a date in the past, counted as tool failures. RISE
and drift now read this PC's own rows only, and the failure share leaves out refused calls and the caller's mistakes."""

import sqlite3
import time

from syrax import rise
from syrax.journal import Journal, misuse


def setup(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("own work")
    for i, (kind, out) in enumerate([("tool.completed", "ok"), ("tool.completed", "ok"), ("tool.failed", "Error: boom"),
                                     ("tool.failed", "Error: learn refused: knowledge_id 3 does not support the claim: cite")]):
        name = "learn" if "learn" in out else "python_execute"
        j.record_sync(kind, {"id": f"c{i}", "name": name, "ok": kind == "tool.completed", "output": out}, task_id=t)
    j.record_sync("tool.failed", {"id": "r", "name": "python_execute", "ok": False, "refused": True, "output": "Error: refused"}, task_id=t)
    j.close()
    db = sqlite3.connect(tmp_path / "j.db")  # merged rows from another PC, as the import leaves them: ids below zero
    now = time.time()
    for i in range(10):
        db.execute("INSERT INTO events (id, ts, task_id, type, payload, seq) VALUES (?, ?, NULL, 'tool.failed', ?, 0)",
                   (-10_000_000 + i, now - 60, '{"name": "python_execute", "output": "Error: windows failure"}'))
    db.commit()
    db.close()
    return tmp_path / "j.db"


def test_the_failure_share_counts_this_pcs_real_failures_only(tmp_path):
    path = setup(tmp_path)
    row = next(m for m in rise.measure(path)["metrics"] if m["id"] == "tool_failures")
    assert row["last"]["value"] == round(100 / 3, 1) and row["last"]["detail"] == "1/3"  # 2 ok, 1 real failure


def test_the_learn_refusal_and_a_past_date_are_the_callers_mistake():
    assert misuse("learn", "Error: learn refused: knowledge_id 3 does not support the claim: cite the rows whose text does")
    assert misuse("flight_search", "Error: flight_search: 2026-06-01 is in the past")
    assert not misuse("python_execute", "Error: boom")
