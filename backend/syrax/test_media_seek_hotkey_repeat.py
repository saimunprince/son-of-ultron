"""2026-11-25 (ideas from the Mark-LVII JARVIS project, SYRAX's own code): media "seek +30" / "seek -10" / "seek 1:20"
moves the playing position and reads it back before and after (playerctl on Linux, the Windows media session, Music on
macOS), undo can go back to the old position, and hotkey "ctrl+tab x3" / "down*5" presses the keys that many times
(at most 20) with the own-window refusal unchanged. Every runner, session and key backend is faked: nothing plays or
is pressed on the test machine."""

import asyncio

import pytest

from syrax import desktop as D
from syrax import permissions, undo, wininput, winctl


def act(action, **kw):
    return asyncio.run(D.DesktopControl().execute(action=action, **kw))


# ---- seek parsing


@pytest.mark.parametrize("value, want", [("seek +30", ("+", 30.0)), ("seek -10", ("-", 10.0)), ("seek 1:20", ("", 80.0)),
                                         ("seek 80", ("", 80.0)), ("Seek to 1:02:05", ("", 3725.0)), ("seek +15s", ("+", 15.0))])
def test_seek_values(value, want):
    assert D.parse_seek(value) == want


@pytest.mark.parametrize("value", ["seek", "seek forward", "seek 1:2:3:4", "seek +-5", "seek abc"])
def test_a_bad_seek_value_is_a_clear_error(value, monkeypatch):
    monkeypatch.setattr(D, "WINDOWS", False)
    monkeypatch.setattr(D, "MACOS", False)
    r = act("media", value=value)
    assert r.error and "seek +30" in r.error


def test_clock():
    assert (D.clock(83.4), D.clock(0), D.clock(3725)) == ("1:23", "0:00", "1:02:05")


# ---- Linux: playerctl


@pytest.fixture
def linux(monkeypatch):
    calls, positions = [], ["80.0", "110.2"]

    async def fake_run(*args, **_):
        calls.append(args)
        if args[:2] == ("playerctl", "position") and len(args) == 2:
            return 0, positions.pop(0) if len(positions) > 1 else positions[0], ""
        if args[:2] == ("playerctl", "metadata"):
            return 0, "Arijit Singh - Sajde", ""
        return 0, "", ""

    monkeypatch.setattr(D, "WINDOWS", False)
    monkeypatch.setattr(D, "MACOS", False)
    monkeypatch.setattr(D, "SEEK_SETTLE", 0)
    monkeypatch.setattr(D.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(D, "_run", fake_run)
    return {"calls": calls, "positions": positions}


def test_linux_relative_seek_reads_the_position_back(linux):
    r = act("media", value="seek +30")
    assert ("playerctl", "position", "30+") in linux["calls"]
    assert r.output == "Seeked +30s in 'Arijit Singh - Sajde': position 1:20 -> 1:50."


def test_linux_back_and_absolute_seek(linux):
    act("media", value="seek -10")
    assert ("playerctl", "position", "10-") in linux["calls"]
    linux["positions"][:] = ["200", "80"]
    r = act("media", value="seek 1:20")
    assert ("playerctl", "position", "80") in linux["calls"]
    assert "to 1:20" in r.output and "3:20 -> 1:20" in r.output


def test_linux_no_player_moves_nothing(monkeypatch, linux):
    async def none(*args, **_):
        linux["calls"].append(args)
        return 1, "", "No players found"

    monkeypatch.setattr(D, "_run", none)
    r = act("media", value="seek +30")
    assert r.error == "No media player is open to seek."
    assert linux["calls"] == [("playerctl", "position")]  # read only, no seek sent


def test_plain_media_commands_are_unchanged(linux):
    assert act("media", value="play").output == "Media play sent."


# ---- Windows: the media session


@pytest.fixture
def win(monkeypatch):
    seen = {}

    async def sessions(self, cmd=None, seek=""):
        seen.update(cmd=cmd, seek=seek)
        return seen.get("data", {"current": "Spotify.exe", "done": True, "before": 80.0, "position": 110.4,
                                 "sessions": [{"app": "Spotify.exe", "status": "Playing", "title": "Sajde"}]})

    monkeypatch.setattr(D, "WINDOWS", True)
    monkeypatch.setattr(D.DesktopControl, "_media_sessions", sessions)
    monkeypatch.setattr(D, "_press_keys", lambda *a, **k: pytest.fail("no media key for a seek"))
    return seen


def test_windows_seek_goes_through_the_session_and_reads_back(win):
    r = act("media", value="seek +30")
    assert (win["cmd"], win["seek"]) == ("seek", "+30")
    assert r.output.startswith("Seeked +30s in Spotify: position 1:20 -> 1:50. Now: ")


def test_windows_seek_refused_or_no_session(win):
    win["data"] = {"current": "Spotify.exe", "done": False, "sessions": []}
    assert "refused the seek" in act("media", value="seek 1:20").error
    win["data"] = {"current": None, "done": None, "sessions": []}
    assert act("media", value="seek -10").error == "No media session is open to seek."


def test_the_windows_script_seeks_and_reports_positions():
    assert "TryChangePlaybackPositionAsync" in D.MEDIA_PS and "position = $after" in D.MEDIA_PS


# ---- macOS: Music


def test_macos_seek_sets_music_player_position(monkeypatch):
    lines, reads = [], ["80", "110"]

    async def osa(*ls, **_):
        lines.extend(ls)
        return 0, (reads.pop(0) if ls[0].endswith("player position") else ""), ""

    monkeypatch.setattr(D, "WINDOWS", False)
    monkeypatch.setattr(D, "MACOS", True)
    monkeypatch.setattr(D, "_osascript", osa)
    r = act("media", value="seek +30")
    assert 'tell application "Music" to set player position to (player position + 30)' in lines
    assert r.output == "Seeked +30s in Music: position 1:20 -> 1:50."


# ---- undo


def test_a_seek_is_undone_by_seeking_back():
    rev = undo.reverse_of("desktop", {"action": "media", "value": "seek +30"}, "Seeked +30s in Spotify: position 1:20 -> 1:50. Now: x")
    assert rev["reverse"] == {"tool": "desktop", "args": {"action": "media", "value": "seek 1:20"}}
    assert undo.reverse_of("desktop", {"action": "media", "value": "seek 1:20"}, "Seeked to 1:20: position now 1:20.") is None


# ---- hotkey repeat

NOTEPAD = {"title": "notes.md - Notepad", "process": "Notepad.exe", "pid": 1}


@pytest.fixture
def keys(monkeypatch):
    pressed = []
    monkeypatch.setattr(D, "WINDOWS", True)
    monkeypatch.setattr(D, "HOTKEY_GAP", 0)
    monkeypatch.setattr(winctl, "foreground", lambda: NOTEPAD)
    monkeypatch.setattr(wininput, "hotkey", lambda spec, b=None: pressed.append(spec) or f"Pressed {spec}.")
    return pressed


@pytest.mark.parametrize("value, want", [("ctrl+tab x3", ("ctrl+tab", 3)), ("down*5", ("down", 5)), ("down * 5", ("down", 5)),
                                         ("ctrl+x", ("ctrl+x", 1)), ("f5", ("f5", 1)), ("ctrl+tab X 2", ("ctrl+tab", 2))])
def test_hotkey_count_parsing(value, want):
    assert D.hotkey_repeat(value) == want


def test_hotkey_repeats_and_says_how_many(keys):
    r = act("hotkey", value="ctrl+tab x3")
    assert keys == ["ctrl+tab"] * 3
    assert r.output.startswith("Pressed ctrl+tab 3 times.")


def test_hotkey_repeat_is_capped(keys):
    for v in ("down*21", "down x0"):
        r = act("hotkey", value=v)
        assert r.error and "1 to 20" in r.error
    assert keys == []
    act("hotkey", value="down*20")
    assert len(keys) == 20


def test_a_single_hotkey_is_unchanged(keys):
    assert act("hotkey", value="alt+f4").output.startswith("Pressed alt+f4.")
    assert keys == ["alt+f4"]


def test_a_failure_part_way_says_how_many_went_out(monkeypatch, keys):
    n = []

    def flaky(spec, b=None):
        n.append(spec)
        if len(n) == 3:
            raise RuntimeError("E-STOP")
        return "ok"

    monkeypatch.setattr(wininput, "hotkey", flaky)
    assert act("hotkey", value="down*5").error == "E-STOP (after 2 of 5 presses of down)"


def test_own_window_refusal_still_applies_to_a_repeat(monkeypatch, keys):
    monkeypatch.setattr(D, "front_read", lambda: ("'SYRAX - Google Chrome' (chrome.exe)", "SYRAX - Google Chrome"))
    r = act("hotkey", value="ctrl+tab x3")
    assert r.error and "SYRAX's own" in r.error and keys == []


def test_a_repeated_enter_is_still_a_send():
    for v in ("enter x3", "enter*2", "ctrl+enter x2"):
        assert permissions.submits_text({"action": "hotkey", "value": v}), v
    assert not permissions.submits_text({"action": "hotkey", "value": "shift+enter x3"})


def test_the_tool_describes_seek_and_repeat():
    desc = D.DesktopControl().parameters["properties"]["value"]["description"]
    assert "seek +30" in desc and "ctrl+tab x3" in desc
