"""Live 2026-10-25 (Prince): "play some random music" opened a YouTube search page, "play it your self" pressed the
play/pause key (a toggle: it pauses what plays) and the tool said "Media play sent.", and the answers said "Media is
playing" four times while the human said nothing played. On Windows `desktop media` now reads Windows' own media
sessions (which app plays what, and whether it plays) and drives the current session (play is play, not a toggle);
every media answer says what plays after it. Typing, keys and clicks at a point name the window in front after them
(live: "Typed 5 characters into the focused window.", Enter, "Message sent to bro bhi"). PowerShell and the window
reader are faked here: nothing plays, pauses or types on the machine running the tests."""

import asyncio
import json

import pytest

from syrax import desktop as D
from syrax import wininput, winctl

PLAYING = {"current": "Chrome", "done": None, "sessions": [{"app": "Chrome", "status": "Playing", "title": "Sajde"}]}
PAUSED = {"current": "Chrome", "done": None, "sessions": [{"app": "Chrome", "status": "Paused", "title": "Sajde"}]}
NONE = {"current": None, "done": None, "sessions": []}


@pytest.fixture
def ps(monkeypatch):
    """Windows' media sessions as PowerShell would report them; records each call's command and the keys pressed."""
    state = {"answers": [], "cmds": [], "keys": [], "fail": None}

    async def fake(script, timeout=15, extra_env=None):
        state["cmds"].append((extra_env or {}).get("SYRAX_MEDIA_CMD"))
        if state["fail"]:
            return 1, "", state["fail"]
        return 0, json.dumps(state["answers"].pop(0)), ""

    monkeypatch.setattr(D, "WINDOWS", True)
    monkeypatch.setattr(D, "_powershell", fake)
    monkeypatch.setattr(D, "_press_keys", lambda *names, times=1: state["keys"].extend(names))
    return state


def media(value):
    return asyncio.run(D.DesktopControl().execute(action="media", value=value))


def test_status_says_what_plays_in_which_app(ps):
    ps["answers"] = [PLAYING]
    r = media("status")
    assert r.error is None and r.output == "Playing: 'Sajde' in Chrome."
    assert ps["cmds"] == [""] and ps["keys"] == []  # reading presses nothing


def test_status_with_nothing_open_says_so(ps):
    ps["answers"] = [NONE]
    assert media("status").output == "No media session is open: nothing is playing or paused in any app."


def test_play_goes_to_the_current_session_and_says_what_plays_after(ps):
    ps["answers"] = [{**PLAYING, "done": True}]
    r = media("play")
    assert r.output == "Play taken by Chrome. Now: Playing: 'Sajde' in Chrome."
    assert ps["cmds"] == ["play"] and ps["keys"] == []  # the session's own play, not the play/pause toggle


def test_a_session_that_refuses_says_so_and_the_state_shows_it(ps):
    ps["answers"] = [{**PAUSED, "done": False}]
    assert media("play").output == "Play refused by Chrome. Now: Paused: 'Sajde' in Chrome."


def test_with_no_session_the_key_is_pressed_and_the_state_read_again(ps, monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(D.asyncio, "sleep", lambda s: real_sleep(0))
    ps["answers"] = [NONE, NONE]
    r = media("play")
    assert ps["keys"] == ["play_pause"] and ps["cmds"] == ["play", ""]
    assert r.output == ("No media session was open to take play, so the play/pause key was pressed. "
                        "Now: No media session is open: nothing is playing or paused in any app.")


def test_when_windows_cannot_be_read_the_answer_says_so(ps):
    ps["fail"] = "Unable to find type [Windows.Media.Control...]"
    r = media("status")
    assert r.error.startswith("The playback state could not be read: Unable to find type")
    r = media("next")
    assert ps["keys"] == ["next"] and r.output.startswith("Pressed the next key; whether anything plays could not be read")


def test_every_session_is_listed_and_a_private_title_is_not_written_down(ps):
    ps["answers"] = [{"current": "Spotify.exe", "done": None, "sessions": [
        {"app": "Spotify.exe", "status": "Paused", "title": "Focus mix"},
        {"app": "Chrome", "status": "Playing", "title": "Gmail - Inbox (3)"}]}]
    assert media("status").output == "Paused: 'Focus mix' in Spotify; Playing: '[title not recorded: it looked private]' in Chrome."


@pytest.mark.parametrize("app_id, name", [
    ("Chrome", "Chrome"), ("Spotify.exe", "Spotify"), ("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic", "Microsoft.ZuneMusic"),
    ("", "an app"), (None, "an app"),
])
def test_app_names(app_id, name):
    assert D.media_app(app_id) == name


def test_a_bad_value_is_an_error(ps):
    assert media("louder").error.startswith("media value must be play, pause, toggle, next, previous, stop or status")


# ——— where the hands landed ———


@pytest.fixture
def hands(monkeypatch):
    monkeypatch.setattr(D, "WINDOWS", True)
    monkeypatch.setattr(wininput, "type_text", lambda text, b=None, pause=0.004: f"Typed {len(text)} characters into the focused window.")
    monkeypatch.setattr(wininput, "hotkey", lambda spec, b=None: f"Pressed {spec}.")
    monkeypatch.setattr(wininput, "click", lambda where, how="left", b=None: f"Left-clicked at {where}.")
    front = {"w": {"title": "bro bhi – Telegram", "process": "Telegram.exe", "pid": 7}}
    monkeypatch.setattr(winctl, "foreground", lambda: front["w"])
    return front


def act(action, **kw):
    return asyncio.run(D.DesktopControl().execute(action=action, **kw))


def test_typing_keys_and_clicks_name_the_window_in_front(hands):
    assert act("type_text", value="hello").output == "Typed 5 characters into the focused window. In front now: 'bro bhi – Telegram' (Telegram.exe)."
    assert act("hotkey", value="enter").output == "Pressed enter. In front now: 'bro bhi – Telegram' (Telegram.exe)."
    assert act("click", target="1877,159").output == "Left-clicked at 1877,159. In front now: 'bro bhi – Telegram' (Telegram.exe)."


def test_a_private_title_in_front_is_not_written_down(hands):
    hands["w"] = {"title": "Sign in - Google Accounts - password", "process": "chrome.exe", "pid": 9}
    assert act("type_text", value="x").output.endswith("In front now: '[title not recorded: it looked private]' (chrome.exe).")


def test_nothing_in_front_and_an_unreadable_front_are_said_plainly(hands, monkeypatch):
    hands["w"] = None
    assert act("hotkey", value="enter").output == "Pressed enter. Nothing is in front now."

    def broken():
        raise OSError("no desktop")

    monkeypatch.setattr(winctl, "foreground", broken)
    assert act("hotkey", value="enter").output == "Pressed enter."


def test_a_refused_hand_action_stays_an_error(hands, monkeypatch):
    def stopped(text, b=None, pause=0.004):
        raise wininput.Stopped("stopped: the human moved the mouse")

    monkeypatch.setattr(wininput, "type_text", stopped)
    r = act("type_text", value="hello")
    assert r.error == "stopped: the human moved the mouse" and not r.output
