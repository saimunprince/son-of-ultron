"""Live 2026-10-17: objective 267's release was cut by a shutdown after its
preflight passed. The release had kept the diff as a snapshot, but the next
attempt started from zero because nothing pointed to it. When a restart
reopens an objective, the interrupted task joins its attempts log with the
kept diff (no attempt counted), and the brief points to it."""

from syrax.autonomy import brief_evidence
from syrax.test_autonomy import make

GOAL = "Brain latency. Three steps, one apply_patch each, then one release."


def test_a_restart_points_the_next_attempt_at_the_interrupted_diff(tmp_path):
    j, core, a = make(tmp_path, tools=["terminate"])
    o = j.add_objective_sync(GOAL, "test", 2, "human", {"kind": "change_released"})
    j.update_objective_sync(o["id"], status="ACTIVE", note="cycle picked this objective")
    t = j.start_task_sync(GOAL, kind="autonomous")
    j.record_sync("tool.started", {"id": "p", "name": "apply_patch", "args": {"diff": "--- a/x"}}, task_id=t)
    j.record_sync("tool.completed", {"id": "p", "name": "apply_patch", "ok": True, "output": "patched"}, task_id=t)
    j.record_sync("code.changed", {"files": {"backend/syrax/brains.py": "M", "backend/syrax/test_brain_ms.py": "??"},
                                   "snapshot": "backend/config/rollback/1792068659-60dbf24.patch"}, task_id=t)
    j.record_sync("task.interrupted", {"error": "interrupted at step 26 during tool:release"}, task_id=t)
    assert j.task(t)["status"] == "INTERRUPTED"
    assert a.recover_active("process restarted") == 1
    row = j.objective(o["id"])
    assert row["status"] == "OPEN" and row["attempts"] == 0
    entry = row["progress"]["attempts_log"][-1]
    assert entry["verdict"] == "INTERRUPTED" and entry["task_id"] == t and entry["kept"].endswith("60dbf24.patch")
    assert entry["kept_files"] == ["backend/syrax/brains.py", "backend/syrax/test_brain_ms.py"]
    assert "kept as a diff at backend/config/rollback/1792068659-60dbf24.patch" in brief_evidence(row)
    j.update_objective_sync(o["id"], status="ACTIVE", note="picked again")
    a.recover_active("process restarted")
    assert len(j.objective(o["id"])["progress"]["attempts_log"]) == 1  # the same task is logged once


def test_no_entry_when_nothing_was_interrupted(tmp_path):
    j, core, a = make(tmp_path, tools=["terminate"])
    o = j.add_objective_sync(GOAL, "test", 2, "human", {"kind": "change_released"})
    j.update_objective_sync(o["id"], status="ACTIVE", note="cycle picked this objective")
    a.recover_active("loop stopped")
    assert "attempts_log" not in (j.objective(o["id"])["progress"] or {})
