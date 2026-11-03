"""Audit 2026-11-01 (F16): the "Commits SYRAX made to itself" definition said every commit passed a second brain's
review, but a change the human asked for in the chat lands on the human's own approval of the shown diff when no
second brain can review it (F10). The definition says so."""

from syrax import rise


def test_the_own_commit_definition_names_the_human_approval():
    m = {x.id: x for x in rise.METRICS}["own_commits"]
    assert "second brain's review" in m.definition and "the human's own approval" in m.definition
