"""Review 2026-10-27: a message sent through the desktop (SYRAX types into Telegram or WhatsApp and presses Enter) was
classed SYSTEM like any keystroke, so the send gate never asked, the intent ledger never held a repeat, and a true
"Message sent" after one was taken for an unbacked claim. Live 2026-10-25 (task cb8cc6cf3028): an invented "hello"
was typed, Enter went into the wrong window, and the answer said "Message sent". A desktop action that submits text
(Enter, ctrl+Enter, a typed newline, a click on Send) while a messaging app is in front is now an EXTERNAL_WRITE.
The window reader, the keyboard and the brain are faked: nothing is typed or pressed on the machine running this."""

import pytest

from syrax import desktop as D
from syrax import permissions as P
from syrax import wininput, winctl
from syrax.agent import OUTCOME_NOTE, classes_of
from syrax.intent import HELD, summary
from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, drain_until_idle, reply, script, server  # noqa: F401

TELEGRAM = {"title": "bro bhi – Telegram", "process": "Telegram.exe", "pid": 7}
FRONT = "'bro bhi – Telegram' (Telegram.exe)"
SPARE = reply("(spare)")


@pytest.fixture
def front(monkeypatch):
    """The window in front, as winctl.foreground reports it (desktop.front_window reads it); set w to change it."""
    state = {"w": TELEGRAM}
    monkeypatch.setattr(D, "WINDOWS", True)
    monkeypatch.setattr(winctl, "foreground", lambda: state["w"])
    return state


def level(args):
    return P.classify("desktop", args).level


# ——— what counts as a send ———


def test_enter_in_a_messaging_app_is_a_send(front):
    d = P.classify("desktop", {"action": "hotkey", "value": "enter"})
    assert (d.level, d.reason, d.targets) == (P.EXTERNAL_WRITE, "sends a message in Telegram", [FRONT])
    for keys in ("Enter", "return", "ctrl+enter", "ctrl + Enter"):
        assert level({"action": "hotkey", "value": keys}) == P.EXTERNAL_WRITE, keys
    assert level({"action": "type_text", "value": "hello\nsee you"}) == P.EXTERNAL_WRITE  # type_text presses Enter for \n
    assert level({"action": "click_text", "target": "Send"}) == P.EXTERNAL_WRITE


def test_typing_alone_a_new_line_and_other_keys_are_not_a_send(front):
    assert level({"action": "type_text", "value": "hello"}) == P.SYSTEM
    assert level({"action": "type_text", "value": "hello\n"}) == P.SYSTEM  # the desktop tool strips the value: no Enter
    assert level({"action": "hotkey", "value": "shift+enter"}) == P.SYSTEM  # a new line in the chat
    assert level({"action": "hotkey", "value": "ctrl+c"}) == P.SYSTEM
    assert level({"action": "click_text", "target": "Save"}) == P.SYSTEM


@pytest.mark.parametrize("window, app", [
    ({"title": "WhatsApp", "process": "WhatsApp.Root.exe"}, "WhatsApp"),
    ({"title": "WhatsApp - Google Chrome", "process": "chrome.exe"}, "WhatsApp"),
    ({"title": "web.whatsapp.com - Microsoft Edge", "process": "msedge.exe"}, "WhatsApp"),
    ({"title": "Chat | Rahim | Microsoft Teams", "process": "ms-teams.exe"}, "Microsoft Teams"),
    ({"title": "Signal", "process": "Signal.exe"}, "Signal"),
    ({"title": "#general - Discord", "process": "Discord.exe"}, "Discord"),
    ({"title": "Messenger | Facebook - Google Chrome", "process": "chrome.exe"}, "Messenger"),
])
def test_the_messaging_apps_are_known_by_their_window(front, window, app):
    front["w"] = {**window, "pid": 1}
    d = P.classify("desktop", {"action": "hotkey", "value": "enter"})
    assert (d.level, d.reason) == (P.EXTERNAL_WRITE, f"sends a message in {app}")


@pytest.mark.parametrize("window", [
    {"title": "notes.md - Notepad", "process": "Notepad.exe"},
    {"title": "Signal processing.pdf - Adobe Acrobat", "process": "Acrobat.exe"},
    {"title": "agent.py - Visual Studio Code", "process": "Code.exe"},
    None,  # nothing in front
])
def test_enter_anywhere_else_stays_system(front, window):
    front["w"] = window
    assert level({"action": "hotkey", "value": "enter"}) == P.SYSTEM


def test_an_unreadable_front_window_keeps_it_system(front, monkeypatch):
    def broken():
        raise OSError("no desktop")

    monkeypatch.setattr(winctl, "foreground", broken)
    assert level({"action": "hotkey", "value": "enter"}) == P.SYSTEM
    monkeypatch.setattr(D, "front_window", broken)
    assert level({"action": "hotkey", "value": "enter"}) == P.SYSTEM


# ——— the gate ———


def verdict(goal, kind="conversation", args=None):
    return P.decide(P.classify("desktop", args or {"action": "hotkey", "value": "enter"}), kind, goal).action


def test_the_humans_words_naming_the_send_allow_it(front):
    assert verdict("send message to bro bhi") == "allow"
    assert verdict("bro bhi ke hello pathao telegram e") == "allow"
    front["w"] = {"title": "WhatsApp", "process": "WhatsApp.Root.exe", "pid": 3}
    assert verdict("reply ok on whatsapp") == "allow"
    assert verdict("msg rahim that I am late") == "allow"


def test_words_that_do_not_name_a_send_are_asked_about(front):
    assert verdict("type hello in telegram and press enter") == "ask"
    assert verdict("open telegram") == "ask"


def test_a_send_named_for_another_app_is_asked_about(front):
    assert verdict("send hello to bro bhi on whatsapp") == "ask"  # Telegram is in front
    assert verdict("send hello to bro bhi on telegram") == "allow"


def test_a_quality_run_sends_only_on_the_requests_words_and_own_work_never(front):
    assert verdict("send hello to bro bhi", "eval") == "allow"
    assert verdict("type hello and press enter", "eval") == "refuse"
    assert verdict("send hello to bro bhi", "autonomous") == "refuse"


# ——— the claim and the ledger ———


def test_a_send_through_the_desktop_backs_a_sent_claim(front):
    args = {"action": "hotkey", "value": "enter"}
    assert {"desktop", "send"} <= classes_of("desktop", P.classify("desktop", args).level, args)


def test_the_ledger_summary_says_which_keys():
    assert summary("desktop", {"action": "hotkey", "value": "enter"}) == "desktop hotkey: enter"
    assert summary("desktop", {"action": "click_text", "target": "Send"}) == "desktop click_text: Send"


@pytest.fixture
def hands(front, monkeypatch):
    """The keyboard: what was typed and pressed; `fail` makes the next key press fail with that text."""
    state = {"done": [], "fail": None}

    def hotkey(spec, b=None):
        state["done"].append(("keys", spec))
        if state["fail"]:
            why, state["fail"] = state["fail"], None
            raise RuntimeError(why)
        return f"Pressed {spec}."

    monkeypatch.setattr(wininput, "type_text", lambda text, b=None, pause=0.004: state["done"].append(("type", text))
                        or f"Typed {len(text)} characters into the focused window.")
    monkeypatch.setattr(wininput, "hotkey", hotkey)
    return state


def run(goal, ws_steps=None):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": goal})
        if ws_steps:
            ws_steps(ws)
        seen = drain_until_idle(ws)
    return get_journal().tasks()[0], seen


def test_live_a_named_send_runs_without_a_question_and_its_claim_stands(script, hands):
    script.queue = [call("desktop", {"action": "type_text", "value": "hello"}, cid="t"),
                    call("desktop", {"action": "hotkey", "value": "enter"}, cid="k"),
                    reply("Message sent to bro bhi on Telegram."),
                    SPARE]  # what a nudge about an unbacked "sent" would take
    task, seen = run("send hello to bro bhi on telegram")
    assert hands["done"] == [("type", "hello"), ("keys", "enter")]
    assert not any(e["type"] == "ask" for e in seen)
    assert task["result"] == "Message sent to bro bhi on Telegram." and OUTCOME_NOTE.split(":")[0] not in task["result"]
    assert "send" in core_mod.get_core().agent.acted and script.queue == [SPARE]
    events = get_journal().events(task["task_id"])
    rec = [e["payload"] for e in events if e["type"] == "intent.recorded"]
    assert [r["summary"] for r in rec] == ["desktop hotkey: enter"]  # the Enter is the send the ledger keys


def test_live_enter_the_human_did_not_ask_for_is_asked_about_and_a_no_keeps_it(script, hands):
    script.queue = [call("desktop", {"action": "type_text", "value": "hello"}, cid="t"),
                    call("desktop", {"action": "hotkey", "value": "enter"}, cid="k"),
                    reply("I did not send it: you said no.")]

    asked = []

    def answer_no(ws):
        for _ in range(80):  # the question, or the task's end without one
            e = ws.receive_json()
            if e["type"] == "ask":
                asked.append(e["question"])
                ws.send_json({"type": "answer", "text": "no"})
                return
            if e["type"] == "state" and e.get("state") == "idle":
                raise AssertionError("the Enter was never asked about")

    task, _ = run("open telegram and type hello for bro bhi", answer_no)
    assert len(asked) == 1 and "sends a message in Telegram" in asked[0]
    assert hands["done"] == [("type", "hello")]  # typed, never submitted


def test_an_enter_that_may_have_gone_out_is_not_pressed_again(script, hands):
    hands["fail"] = "SendInput timed out"
    script.queue = [call("desktop", {"action": "type_text", "value": "hello"}, cid="t1"),
                    call("desktop", {"action": "hotkey", "value": "enter"}, cid="k1"),
                    call("desktop", {"action": "type_text", "value": "hello"}, cid="t2"),
                    call("desktop", {"action": "hotkey", "value": "enter"}, cid="k2"),
                    reply("Not sent again: the first Enter may already have gone out.")]
    task, _ = run("send hello to bro bhi on telegram")
    assert hands["done"].count(("keys", "enter")) == 1
    kinds = [e["type"] for e in get_journal().events(task["task_id"])]
    assert "intent.uncertain" in kinds and "intent.refused" in kinds
    failed = [e["payload"] for e in get_journal().events(task["task_id"]) if e["type"] == "tool.failed"]
    assert any(HELD.split(":")[0] in str(p.get("output")) for p in failed)
