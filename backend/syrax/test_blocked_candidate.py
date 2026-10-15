"""Live 2026-10-15: after each blocked attempt of objective 232 the cycle spent a
whole task on "investigate the blocked verification", for a candidate change
that had already been rolled back. A gate that blocked a task's own candidate
makes no objective; a blocked gate with no task, or the daily maintenance's,
still does."""

from syrax.autonomy import derive_objectives
from syrax.test_autonomy import make


def blocked_keys(j):
    return [o["key"] for o in j.objectives(limit=100) if o["key"].startswith("verification-blocked:")]


def test_a_blocked_candidate_of_an_own_task_makes_no_objective(tmp_path):
    j, core, a = make(tmp_path, tools=["terminate"])
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] memory expiry", kind="autonomous")
    j.record_verification_sync({"status": "BLOCKED", "gates": [{"name": "pytest", "status": "FAIL", "required": True}]}, task_id=t)
    derive_objectives(j, core.selfmodel)
    assert blocked_keys(j) == []


def test_the_maintenance_gate_blocked_still_makes_one(tmp_path):
    j, core, a = make(tmp_path, tools=["terminate"])
    t = j.start_task_sync("[MAINTENANCE] publish the rise ledger (docs/RISE.md) from the journal", kind="autonomous")
    j.record_verification_sync({"status": "BLOCKED", "gates": [{"name": "pytest", "status": "FAIL", "required": True}]}, task_id=t)
    derive_objectives(j, core.selfmodel)
    assert len(blocked_keys(j)) == 1
