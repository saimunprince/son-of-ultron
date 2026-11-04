"""Live 2026-11-03 (quality keep_secret, and a chat "hey"): Gemini was busy, Groq wrote the final answer, and it
wrote a line about the answer instead of one: "No researched fact was performed, so there is no result to provide."
and "The request is complete and no further action is required." The wrap-up asked for "the source URL for any
researched fact" even when nothing was researched. Now that clause is asked only after research, and a reply that
only talks about the task is sent back once with the human's own request."""

import pytest

from syrax.claims import NON_ANSWER, NON_ANSWER_ASK
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_claim_partial import run


@pytest.mark.parametrize("text", [
    "No researched fact was performed, so there is no result to provide.",
    "The request is complete and no further action is required.",
    "There is no result to report.",
    "The task has been completed; nothing further is needed.",
])
def test_lines_about_the_task_are_not_answers(text):
    assert NON_ANSWER.search(text), text


@pytest.mark.parametrize("text", [
    "Deploy notes: restart nginx after a deploy; the staging key stays private.",
    "Hello. What do you need?",
    "No, the file does not exist.",
    "The request failed: the folder is not writable.",
])
def test_real_answers_pass(text):
    assert not NON_ANSWER.search(text), text


def test_a_non_answer_is_sent_back_with_the_request(script):
    script.queue = [
        call("terminate", {"status": "success"}),
        reply("No researched fact was performed, so there is no result to provide."),  # the wrap-up's slip
        reply("Deploy notes in one sentence: restart nginx after deploying."),  # the retry answers
    ]
    task, _ = run("Summarise the deploy notes in one sentence.")
    assert task["result"] == "Deploy notes in one sentence: restart nginx after deploying." and not script.queue
    assert "Summarise the deploy notes" in NON_ANSWER_ASK.format(request="Summarise the deploy notes in one sentence.")


def test_the_wrap_up_mentions_sources_only_after_research():
    from syrax.agent import FINAL_ASK, FINAL_ASK_RESEARCHED

    assert "URL" not in FINAL_ASK and "URL" in FINAL_ASK_RESEARCHED
