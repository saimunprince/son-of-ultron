"""Live 2026-10-14 (objective 224, attempt 3): thirty steps of edits, no
release, and the final said "implemented ... and verified"; the edits were
rolled back. When a brief asks for a release and edits were made but no
release committed them, the answer says so."""

from syrax.agent import NOT_RELEASED_NOTE, SyraxAgent
from syrax.autonomy import RELEASE_MARK


def agent(changed, committed):
    a = SyraxAgent.model_construct()
    a.changed, a.release_committed = changed, committed
    return a


def test_unreleased_edits_are_named_only_when_a_release_was_asked_and_none_landed():
    brief = f"[AUTONOMOUS OBJECTIVE] ... The objective {RELEASE_MARK}."
    assert agent(True, False)._unreleased_edits(brief)
    assert not agent(True, True)._unreleased_edits(brief)
    assert not agent(False, False)._unreleased_edits(brief)
    assert not agent(True, False)._unreleased_edits("open notepad")
    assert "rolled back" in NOT_RELEASED_NOTE and "objective stays open" in NOT_RELEASED_NOTE
