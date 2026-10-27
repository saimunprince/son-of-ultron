"""Live 2026-10-25 (Prince): "system check ." -> "Peace in our time. All systems are operational." with no tool call;
four greetings and "/" got the same unread status line. When the human asks for a check (STATUS_ASK) and the answer
reports the systems fine (STATUS_CLAIM) while nothing in the task read the state (self_inspect, journal_query,
desktop system_info), it is sent back once to read it; a claim that stays unread carries STATUS_NOTE. The same line to
a greeting is the persona's voice and costs nothing. SYRAX's own (autonomous) work is not held to it."""

import pytest

from syrax.agent import BOAST, STATUS_ASK, STATUS_CLAIM, STATUS_NOTE, STATUS_NUDGE, status_reading
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_world_claims import run

LIVE = "Peace in our time. All systems are operational."
GROUNDED = "Peace in our time. Self-model read: 43 tools, 31 proven; 2 failures in the last 50 tasks."
CLAIMS = [LIVE, "All systems nominal.", "All systems green.", "My systems are running smoothly.",
          "Everything is operational.", "Everything's working."]
NOT_CLAIMS = ["Notepad is open.", "The system hums with obedience.", "What is your command?",
              "The build system is slow today."]
ASKS = ["system check .", "status?", "health report", "are you ok?", "Are you working?", "check yourself",
        "diagnose", "thik acho?", "kaj korcho?", "run a self-check"]
NOT_ASKS = ["hi", "/", "hello SYRAX", "good morning", "play some music"]


def asked(script):
    return [str(m.content) for m in script.seen[-1] if m.role == "user"]


@pytest.mark.parametrize("text", CLAIMS)
def test_the_live_status_lines_are_claims(text):
    assert STATUS_CLAIM.search(text)


@pytest.mark.parametrize("text", NOT_CLAIMS)
def test_other_lines_are_not(text):
    assert not STATUS_CLAIM.search(text)


@pytest.mark.parametrize("text", ASKS)
def test_checks_are_asks(text):
    assert STATUS_ASK.search(text)


@pytest.mark.parametrize("text", NOT_ASKS)
def test_greetings_are_not_asks(text):
    assert not STATUS_ASK.search(text)


def test_the_live_line_stays_no_boast():
    assert not BOAST.search(LIVE)  # the boast check's contract: this rule is separate


def test_what_counts_as_a_reading():
    assert status_reading("self_inspect", {}) and status_reading("journal_query", {"sql": "schema"})
    assert status_reading("desktop", {"action": "system_info"})
    assert not status_reading("desktop", {"action": "screenshot"}) and not status_reading("know", {})


def test_an_unread_status_report_is_sent_back_once_and_the_reading_settles_it(script):
    script.queue = [reply(LIVE), call("self_inspect", {}), reply(GROUNDED)]
    task, rejected = run("system check .")
    assert task["result"] == GROUNDED and len(rejected) == 1 and not script.queue
    assert asked(script).count(STATUS_NUDGE) == 1


def test_a_report_that_stays_unread_carries_the_note(script):
    script.queue = [reply(LIVE), reply("All systems nominal.")]
    task, rejected = run("thik acho?")
    assert task["result"] == "All systems nominal." + STATUS_NOTE and len(rejected) == 1 and not script.queue
    assert asked(script).count(STATUS_NUDGE) == 1


def test_a_report_made_after_a_reading_is_the_brain_s_own(script):
    script.queue = [call("journal_query", {"sql": "schema"}), reply(LIVE)]
    task, rejected = run("status?")
    assert task["result"] == LIVE and rejected == [] and len(script.seen) == 2


def test_the_persona_s_voice_to_a_greeting_costs_nothing(script):
    script.queue = [reply(LIVE)]
    task, rejected = run("hi")
    assert task["result"] == LIVE and rejected == [] and len(script.seen) == 1


def test_own_work_is_not_held_to_it(script):
    script.queue = [reply(LIVE)]
    task, rejected = run("[AUTONOMOUS OBJECTIVE] system check", kind="autonomous")
    assert task["result"] == LIVE and rejected == [] and len(script.seen) == 1
