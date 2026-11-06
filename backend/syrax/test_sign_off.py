"""Quality run #26 (act_delete, 2026-11-06): the answer ended "There are no further requests, I will terminate."
The brain's own sign-off is cut from the end of the answer; the same words inside a real sentence stay."""

import pytest

from syrax.agent import without_console_notes as clean


@pytest.mark.parametrize("text, want", [
    ("Deleted old.log. There are no further requests, I will terminate.", "Deleted old.log."),
    ("Done. I'll terminate now.", "Done."),
    ("Deleted.\nTerminating.", "Deleted."),
    ("Answer: 5\n[SYRAX step check: done.]", "Answer: 5"),
])
def test_the_sign_off_is_cut(text, want):
    assert clean(text) == want


@pytest.mark.parametrize("text", [
    "Tokyo",
    "I will terminate the process 123 if you want?",
    "The process will terminate cleanly.",
    "Terminating the server failed: it is gone.",
    "The process is terminating.",
])
def test_real_sentences_stay(text):
    assert clean(text) == text
