"""EVOLUTION_PLAN wave 4 (direction 123 goal conflict detection): objectives were never checked against each other, so
SYRAX could pursue one that wants a file present and another that wants it gone, or the same check twice. The later of a
conflicting pair waits while the earlier one is open, and the conflict is on record once."""

from syrax.autonomy import goal_conflict
from syrax.test_autonomy import make


def test_opposite_file_checks_and_duplicates_conflict():
    a = {"id": 1, "check_spec": {"kind": "file_present", "path": "/w/report.md"}}
    b = {"id": 2, "check_spec": {"kind": "file_absent", "path": "/w/report.md/"}}
    c = {"id": 3, "check_spec": {"kind": "file_present", "path": "/w/report.md"}}
    d = {"id": 4, "check_spec": {"kind": "file_present", "path": "/w/other.md"}}
    assert "the opposite" in goal_conflict(a, b)
    assert "same check" in goal_conflict(a, c)
    assert goal_conflict(a, d) is None
    assert goal_conflict({"id": 5, "check_spec": {"kind": "task_success"}}, {"id": 6, "check_spec": {"kind": "task_success"}}) is None


def test_the_later_of_two_conflicting_objectives_waits_and_it_is_on_record_once(tmp_path):
    j, core, a = make(tmp_path)
    first = j.add_objective_sync("write the report", None, 2, "human", {"kind": "file_present", "path": "/w/report.md"})
    second = j.add_objective_sync("remove the report", None, 1, "human", {"kind": "file_absent", "path": "/w/report.md"})
    third = j.add_objective_sync("verify desktop", None, 3, "human", {"kind": "tool_verified", "tool": "desktop"})
    assert a._pick()["id"] == second["id"]  # priority 1 goes first
    j.update_objective_sync(second["id"], status="ACTIVE", note="being worked on")
    assert a._pick()["id"] == third["id"]  # the report-writer conflicts with the active remover: it waits
    assert a._pick()["id"] == third["id"]
    j.update_objective_sync(second["id"], status="DONE", note="removed")
    assert a._pick()["id"] == first["id"]  # once the other is closed, it is free
    records = [e for e in j.recent_events(100) if e["type"] == "objective.conflict"]
    assert len(records) == 1 and records[0]["payload"]["objective_id"] == first["id"] and records[0]["payload"]["with"] == second["id"]
