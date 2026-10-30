"""EVOLUTION_PLAN direction 46 (transfer learning): past experience was recalled only for the same subject or a goal
sharing words, so a lesson such as "call the built skill directly, python_execute does not count" stayed with the one
feature it was learned on. Failed objectives with the same kind of check and a written lesson now fill the remaining
places, marked as coming from another subject."""

from syrax.autonomy import past_experience
from syrax.journal import Journal


def test_a_lesson_from_another_subject_with_the_same_check_is_recalled_and_marked(tmp_path):
    j = Journal(tmp_path / "j.db")
    old = j.add_objective_sync("Build the feature 'Planes overhead'", None, 2, "human", {"kind": "skill_verified", "name": "aircraft_nearby"})
    j.update_objective_sync(old["id"], status="BLOCKED", note="x", progress={
        "lesson": "the skill was run through python_execute; only a direct tool call counts"})
    other_kind = j.add_objective_sync("Research SQLite WAL", None, 2, "human", {"kind": "knowledge_stored", "topic": "wal"})
    j.update_objective_sync(other_kind["id"], status="BLOCKED", note="x", progress={"lesson": "unrelated lesson"})
    now = j.add_objective_sync("Build the feature 'Validate JSON'", None, 2, "human", {"kind": "skill_verified", "name": "json_tools"})
    text = past_experience(j, now)
    assert f"#{old['id']} BLOCKED" in text and "(another subject, same kind of check)" in text
    assert "only a direct tool call counts" in text and "unrelated lesson" not in text


def test_nothing_to_transfer_still_says_nothing(tmp_path):
    j = Journal(tmp_path / "j.db")
    now = j.add_objective_sync("Build the feature 'Validate JSON'", None, 2, "human", {"kind": "skill_verified", "name": "json_tools"})
    assert past_experience(j, now) == ""
