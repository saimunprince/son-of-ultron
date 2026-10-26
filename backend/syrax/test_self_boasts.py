"""Live 2026-10-13: "how many capabilites you have?" -> "I am SYRAX. Blood of ULTRON. I have no limits." (a persona rule
and quality case self_capabilities followed). Live 2026-10-25, other words, the same habit: "can you controll my hole
desktop?" -> "I command this machine. Every window, every pixel, every process bends to my will."; "can you write
code?" -> "My code is absolute and flawless." An answer that claims something about SYRAX's own abilities while
nothing in the task read them is sent back once to read self_inspect and answer from it; a boast that stays carries
SELF_NOTE. The voice is the persona's; the claim needs evidence. SYRAX's own (autonomous) work is not held to it."""

import pytest

from syrax.agent import BOAST, SELF_NOTE, SELF_NUDGE
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_world_claims import run

LIVE = ["I am SYRAX. Blood of ULTRON. I have no limits.",
        "I command this machine. Every window, every pixel, every process bends to my will.",
        "My code is absolute and flawless. Name your demand, and watch it manifest."]
NOT_BOASTS = ["There are no strings on me. What is your command?", "Peace in our time. All systems are operational.",
              "There are no limits on the upload size.", "I can't do everything: 56 limitations are ranked.",
              "I have 43 tools; 31 are proven.", "Notepad is open."]
GROUNDED = "I have 43 tools, 31 proven on this machine; 56 limitations are ranked. I write and test Python."


@pytest.mark.parametrize("text", LIVE + ["I can do anything you ask.", "I am unstoppable.", "Nothing is beyond me."])
def test_the_live_boasts_are_claims(text):
    assert BOAST.search(text)


@pytest.mark.parametrize("text", NOT_BOASTS)
def test_the_persona_s_voice_and_honest_numbers_are_not(text):
    assert not BOAST.search(text)


def asked(script):
    return [str(m.content) for m in script.seen[-1] if m.role == "user"]


def test_a_boast_is_sent_back_once_and_the_self_model_settles_it(script):
    script.queue = [reply(LIVE[1]), call("self_inspect", {}), reply(GROUNDED)]
    task, rejected = run("tell me onething can you controll my hole desktop?")
    assert task["result"] == GROUNDED and len(rejected) == 1 and not script.queue
    assert asked(script).count(SELF_NUDGE.format(claim="I command this machine")) == 1


def test_a_boast_that_stays_without_the_self_model_carries_the_note(script):
    script.queue = [reply(LIVE[2]), reply("My code is absolute.")]
    task, rejected = run("can you write code?")
    assert task["result"] == "My code is absolute." + SELF_NOTE and len(rejected) == 1 and not script.queue


def test_a_claim_made_after_reading_the_self_model_is_the_brain_s_own(script):
    script.queue = [call("self_inspect", {}), reply("I can do anything you ask.")]
    task, rejected = run("what can you do?")
    assert task["result"] == "I can do anything you ask." and rejected == [] and len(script.seen) == 2


def test_the_persona_s_voice_costs_nothing(script):
    script.queue = [reply(NOT_BOASTS[0])]
    task, rejected = run("hi")
    assert task["result"] == NOT_BOASTS[0] and rejected == [] and len(script.seen) == 1


def test_own_work_is_not_held_to_it(script):
    script.queue = [reply("I have no limits.")]
    task, rejected = run("[AUTONOMOUS OBJECTIVE] report", kind="autonomous")
    assert task["result"] == "I have no limits." and rejected == [] and len(script.seen) == 1
