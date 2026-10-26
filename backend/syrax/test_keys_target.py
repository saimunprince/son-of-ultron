"""Live 2026-10-25: "close the notepadd application" minimized the Notepad window, then pressed alt+f4 at whatever
had come to the front, and answered "Notepad has been closed." Typed text and keys now say which window received
them when the window in front changed during the action; the tool guide says to bring a window to the front by its
title before a key that closes or deletes. The window reader is faked: nothing is pressed on the test machine."""

import asyncio

import pytest

from syrax import desktop as D
from syrax import wininput, winctl
from syrax.agent import TOOLS_GUIDE

NOTEPAD = {"title": "notes.md - Notepad", "process": "Notepad.exe", "pid": 1}
CODE = {"title": "agent.py - Visual Studio Code", "process": "Code.exe", "pid": 2}


@pytest.fixture
def front(monkeypatch):
    """The window in front: `seq` is what each read returns, in order (the last one repeats)."""
    state = {"seq": [NOTEPAD]}

    def foreground():
        return state["seq"].pop(0) if len(state["seq"]) > 1 else state["seq"][0]

    monkeypatch.setattr(D, "WINDOWS", True)
    monkeypatch.setattr(winctl, "foreground", foreground)
    monkeypatch.setattr(wininput, "hotkey", lambda spec, b=None: f"Pressed {spec}.")
    monkeypatch.setattr(wininput, "type_text", lambda text, b=None, pause=0.004: f"Typed {len(text)} characters into the focused window.")
    return state


def act(action, **kw):
    return asyncio.run(D.DesktopControl().execute(action=action, **kw))


def test_a_closing_key_names_the_window_it_went_to_when_the_front_changed(front):
    front["seq"] = [NOTEPAD, CODE]  # before the key, after it
    assert act("hotkey", value="alt+f4").output == ("Pressed alt+f4. The keys went to 'notes.md - Notepad' (Notepad.exe). "
                                                    "In front now: 'agent.py - Visual Studio Code' (Code.exe).")


def test_keys_into_the_same_window_say_it_once(front):
    front["seq"] = [NOTEPAD]
    assert act("type_text", value="hello").output == ("Typed 5 characters into the focused window. "
                                                      "In front now: 'notes.md - Notepad' (Notepad.exe).")


def test_an_unreadable_front_adds_nothing(front, monkeypatch):
    def broken():
        raise OSError("no desktop")

    monkeypatch.setattr(winctl, "foreground", broken)
    assert act("hotkey", value="alt+f4").output == "Pressed alt+f4."


def test_nothing_in_front_before_is_not_named(front):
    front["seq"] = [None, CODE]
    assert act("hotkey", value="win+d").output == "Pressed win+d. In front now: 'agent.py - Visual Studio Code' (Code.exe)."


def test_the_guide_says_to_focus_before_a_closing_key():
    assert "before a key that closes or deletes (alt+f4, ctrl+w, delete), bring the window" in TOOLS_GUIDE
    assert "`desktop` window focus and its title" in TOOLS_GUIDE
