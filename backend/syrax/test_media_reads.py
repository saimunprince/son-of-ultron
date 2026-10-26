"""Live 2026-10-26: asked what music plays, the brain called `desktop` media "get" first (the word volume and
dark_mode take) and got an error, then "status". The reading words mean status: they only read, never act."""

import pytest

from syrax.test_media_truth import PLAYING, media, ps  # noqa: F401  (ps is a fixture)


@pytest.mark.parametrize("value", ["get", "GET", "state", "now", "current", "info", "what", "status", ""])
def test_a_reading_word_reads_and_never_acts(ps, value):
    ps["answers"] = [PLAYING]
    r = media(value)
    assert r.error is None and r.output == "Playing: 'Sajde' in Chrome."
    assert ps["cmds"] == [""] and ps["keys"] == []


def test_an_unknown_word_is_still_an_error(ps):
    assert media("louder").error.startswith("media value must be")
    assert ps["cmds"] == [] and ps["keys"] == []
