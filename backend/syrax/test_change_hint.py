"""Live 2026-10-14 (objective 224, attempt 1): SYRAX edited with the editor,
missed four times, wrote a test that imported `backend.syrax...` and opened the
running journal, and ran out of steps before `release`. The hint for a
code-change objective names apply_patch, how a test imports and isolates, and
release."""

from syrax.autonomy import BRIEF_HINTS, RELEASE_MARK


def test_the_code_change_hint_names_the_tools_and_the_test_rules():
    h = BRIEF_HINTS["change_released"]
    assert RELEASE_MARK in h
    for must in ("`repo_map`", "`apply_patch`", "`release`", "from syrax.<module> import", "tmp_path", "running journal"):
        assert must in h, must
