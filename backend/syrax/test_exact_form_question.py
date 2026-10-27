"""Review 2026-10-27: exact_form read the question's own content as the answer's form: "Explain why Twitter allows up
to 280 characters." held the answer to 280 characters, "Which of these passwords are under 8 characters: ..." to 8,
"List every single word in notes.txt that appears twice" and "Give a one word answer and then explain why" to one
word. A limit counts where it frames the answer; one word is no form beside a list or an explanation."""

import pytest

from syrax.agent import exact_form


@pytest.mark.parametrize("goal", [
    "Explain why Twitter allows up to 280 characters.",
    "Which of these passwords are under 8 characters: abc, abcdefghij, hunter2?",
    "List every single word in notes.txt that appears twice.",
    "Give a one word answer and then explain why.",
    "Pick one word for the mood, then explain your choice.",
    "Why are SMS messages limited to at most 160 characters?",
])
def test_the_questions_content_is_no_form(goal):
    assert exact_form(goal) is None


@pytest.mark.parametrize("goal, limit", [
    ("Summarise deploy.txt in at most 80 characters.", 80),
    ("Describe it in 40 chars or fewer.", 40),
    ("Name the capital. Name only, max 20 characters.", 20),
    ("Explain why Twitter allows 280 characters; keep it under 100 characters.", 100),
    ("What does the README say? Reply in at most 60 characters.", 60),
    ("Answer within 50 characters: what is DNS?", 50),
])
def test_a_limit_that_frames_the_answer_still_counts(goal, limit):
    assert exact_form(goal)["max_chars"] == limit


@pytest.mark.parametrize("goal", [
    "Describe Python in one word.",
    "Which language, in a single word?",
    "Is Python compiled? Answer with one word: yes or no.",
])
def test_one_word_alone_is_still_a_form(goal):
    assert exact_form(goal)["shape"] == "word"
