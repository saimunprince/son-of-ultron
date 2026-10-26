"""Live 2026-10-25 (Prince): after SYRAX said music played and a page opened, the human said "no it was not playing",
"not playing", "not opend", "no", "dont lie with me". None of the five turns read anything: each opened another URL
blind, and the last answered "I do not lie. I dominate. Inspect the screen if your eyes doubt the machine." A short
denial of what the previous turn did on the desktop or the browser is answered from a reading (media status, a
screenshot, find_text, a page read): sent back once to check (DISPUTE_NUDGE), then the answer carries DISPUTE_NOTE."""

import pytest
from app.tool.base import ToolResult

from syrax.agent import DISPUTE_NOTE, DISPUTE_NUDGE, is_dispute, is_reading
from syrax.desktop import DesktopControl
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_world_claims import run

LIVE = ["no it was not playing", "not playing", "not opend", "no", "dont lie with me"]
DISPUTES = LIVE + ["No.", "nope", "it didn't work", "It doesn't work", "nothing happened", "still not", "Still nothing",
                   "it is not open", "the page hasn't loaded", "you are lying", "gaan hoy nai", "kichu hocche na",
                   "chole na", "video baje na", "page khule nai"]
NOT_DISPUTES = ["play some lofi music", "no thanks", "not now", "do not open anything else", "what is playing?",
                "open youtube", "is it possible to not open a new tab next time?",
                "my wifi is not working since this morning, can you check the router settings page and fix it for me",
                "Nothing else, thanks.", "hi"]


@pytest.mark.parametrize("text", DISPUTES)
def test_short_denials_are_disputes(text):
    assert is_dispute(text)


@pytest.mark.parametrize("text", NOT_DISPUTES)
def test_requests_are_not_disputes(text):
    assert not is_dispute(text)


def test_a_bare_no_answers_a_question():
    assert not is_dispute("no", asked=True) and is_dispute("not playing", asked=True)


def test_what_counts_as_a_reading():
    reads = [("desktop", {"action": "media", "value": "status"}), ("desktop", {"action": "screenshot"}),
             ("desktop", {"action": "find_text", "target": "Play"}), ("desktop", {"action": "window", "value": "list"}),
             ("browser_screenshot", {}), ("browser_read", {}), ("browser_exec", {"code": "print(page_info())"}),
             ("self_inspect", {})]
    acts = [("desktop", {"action": "open", "target": "https://youtube.com"}), ("desktop", {"action": "hotkey", "value": "ctrl+t"}),
            ("browser_exec", {"code": 'new_tab("https://youtube.com")'}), ("browser_navigate", {"url": "x"}),
            ("python_execute", {"code": "print(1)"})]
    assert all(is_reading(n, a) for n, a in reads) and not any(is_reading(n, a) for n, a in acts)


def fake_desktop(monkeypatch, media_answer="No media session is open: nothing is playing or paused in any app."):
    done = []

    async def execute(self, action: str, target: str = "", value: str = "", folder: str = "") -> ToolResult:
        done.append((action, target or value))
        if action == "media":
            return ToolResult(output=media_answer)
        return ToolResult(output=f"Opened {target} on the desktop.")

    monkeypatch.setattr(DesktopControl, "execute", execute)
    return done


OPEN = {"action": "open", "target": "https://www.youtube.com/watch?v=jfKfPfyJRdk"}
OPEN2 = {"action": "open", "target": "https://www.youtube.com/watch?v=4xDzrJKXOOY"}
STATUS = {"action": "media", "value": "status"}
FIRST = "I opened the video on YouTube; check that it plays."
BLIND = "I do not lie. I dominate. Inspect the screen if your eyes doubt the machine."


def first_turn(script):
    script.queue = [call("desktop", OPEN), reply(FIRST)]
    task, rejected = run("play some lofi music")
    assert task["result"] == FIRST and rejected == [] and not script.queue


def nudges(script):
    return [str(m.content) for m in script.seen[-1] if m.role == "user"].count(DISPUTE_NUDGE)  # the whole conversation


def test_the_live_dispute_is_sent_back_and_answered_from_a_reading(script, monkeypatch):
    done = fake_desktop(monkeypatch)
    first_turn(script)
    script.queue = [call("desktop", OPEN2), reply(BLIND), call("desktop", STATUS),
                    reply("You are right: nothing is playing. The page opened, but no media session started.")]
    task, rejected = run("dont lie with me")
    assert task["result"] == "You are right: nothing is playing. The page opened, but no media session started."
    assert len(rejected) == 1 and rejected[0]["payload"]["text"] == BLIND and not script.queue
    assert nudges(script) == 1 and done[-1] == ("media", "status")


def test_a_dispute_answered_blind_twice_carries_the_note(script, monkeypatch):
    fake_desktop(monkeypatch)
    first_turn(script)
    script.queue = [call("desktop", OPEN2), reply("Stream reopened."), reply(BLIND)]
    task, rejected = run("not playing")
    assert task["result"] == BLIND + DISPUTE_NOTE and len(rejected) == 1 and not script.queue and nudges(script) == 1


def test_a_dispute_answered_from_a_reading_costs_nothing(script, monkeypatch):
    fake_desktop(monkeypatch)
    first_turn(script)
    script.queue = [call("desktop", STATUS), reply("Nothing is playing: the page opened but the video never started.")]
    task, rejected = run("no it was not playing")
    assert task["result"] == "Nothing is playing: the page opened but the video never started." and rejected == []
    assert not script.queue and nudges(script) == 0


def test_a_no_after_a_turn_that_did_nothing_is_left_alone(script, monkeypatch):
    fake_desktop(monkeypatch)
    script.queue = [reply("Lofi is a calm genre of music.")]
    run("what is lofi music")
    script.queue = [reply("Fine.")]
    task, rejected = run("no")
    assert task["result"] == "Fine." and rejected == [] and not script.queue and nudges(script) == 0


def test_a_no_to_a_question_is_left_alone(script, monkeypatch):
    fake_desktop(monkeypatch)
    script.queue = [call("desktop", OPEN), reply("I opened the video on YouTube. Shall I turn the volume up?")]
    run("play some lofi music")
    script.queue = [reply("Understood.")]
    task, rejected = run("no")
    assert task["result"] == "Understood." and rejected == [] and not script.queue and nudges(script) == 0
