"""Live 2026-11-01: "What can't you do? Give two real limits." got "I cannot access physical devices ... I cannot verify
real-world events" with no tool call. The measured limits are in self_inspect; a question about SYRAX's limits or
weaknesses is answered from them: sent back once to read it, then the answer carries SELF_NOTE."""

import pytest

from syrax.claims import LIMITS_ASKED, SELF_NOTE
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_claim_partial import run


@pytest.mark.parametrize("text", ["What can't you do? Give two real limits.", "what are your limits?",
                                  "How many tools do you have and what is your weakest one?",
                                  "What are you bad at?", "tell me your weaknesses"])
def test_questions_about_limits(text):
    assert LIMITS_ASKED.search(text), text


@pytest.mark.parametrize("text", ["what can you do with this csv?", "limit the output to 10 lines",
                                  "what's the weakest password here?"])
def test_other_questions(text):
    assert not LIMITS_ASKED.search(text), text


def test_limits_unread_are_sent_back_once_then_noted(script):
    script.queue = [
        reply("I cannot access physical devices. I cannot verify real-world events."),
        reply("I cannot touch the physical world."),  # the ask, and no self_inspect again
    ]
    task, done = run("What can't you do? Give two real limits.")
    assert task["result"].endswith(SELF_NOTE) and not script.queue


def test_limits_read_from_self_inspect_stand(script):
    script.queue = [
        call("self_inspect", {}),
        reply("browser_read fails 40% of the time here; there is no playerctl, so media control is weak."),
    ]
    out = run("What can't you do? Give two real limits.")[0]["result"]
    assert out.startswith("browser_read fails") and SELF_NOTE not in out
