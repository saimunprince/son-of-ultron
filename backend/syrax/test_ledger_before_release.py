"""Audit 2026-11-01 (docs D1): the daily publish wrote RISE, the devlog, the archive and the matrix before its own gate
and commit, so every published page reported its own release as missing (the matrix showed the gate RED from the
morning's blocked run though the publish's gate was GREEN minutes later), and nothing said so. Each page now says
under its title that it shows the state before its own release."""

from syrax import ledger


def test_the_note_goes_under_the_title_once():
    out = ledger.before_release("# SYRAX RISE ledger\n\nbody\n")
    assert out.splitlines()[0] == "# SYRAX RISE ledger" and ledger.BEFORE_RELEASE in out.splitlines()[2]
    assert ledger.before_release(out) == out
