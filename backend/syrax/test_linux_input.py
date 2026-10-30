"""EVOLUTION_PLAN wave 3 (directions 208, 221, 226, 227): on this Linux PC the desktop tool's type_text, hotkey, click and
dark_mode were Windows-only. Wayland lets no ordinary program inject input (xdotool reaches X11 only, ydotool needs
root), so linuxinput drives GNOME's RemoteDesktop portal through a helper under the system python3: GNOME asks the
human once, and a restore token kept in backend/config spares later questions. These tests use a fake helper."""

import json
import os
import stat

import pytest

from syrax import desktop, linuxinput as L


def fake(answer=None, seen=None):
    def runner(request):
        if seen is not None:
            seen.append(json.loads(request))
        return json.dumps(answer or {"ok": True, "token": "tok-1"})
    return runner


@pytest.fixture(autouse=True)
def token_file(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "TOKEN_FILE", tmp_path / "portal.token")
    return tmp_path / "portal.token"


def test_keysyms_and_hotkeys():
    assert L.keysym("a") == ord("a") and L.keysym("é") == 0xE9 and L.keysym("ক") == 0x01000000 + ord("ক")
    assert L.keysym("\n") == L.KEYSYMS["enter"]
    assert L.parse_hotkey("ctrl+shift+t") == [0xFFE3, 0xFFE1, ord("t")]
    with pytest.raises(ValueError):
        L.parse_hotkey("ctrl+nosuchkey")


def test_typing_presses_and_releases_each_character_and_keeps_the_token(token_file):
    seen = []
    assert L.type_text("hi", runner=fake(seen=seen)) == "Typed 2 characters into the focused window."
    assert seen[0]["actions"] == [["key", 104, True], ["key", 104, False], ["key", 105, True], ["key", 105, False]]
    assert seen[0]["token"] == "" and token_file.read_text() == "tok-1"
    assert stat.S_IMODE(os.stat(token_file).st_mode) == 0o600
    L.hotkey("ctrl+c", runner=fake(seen=seen))
    assert seen[1]["token"] == "tok-1"  # the restore token goes back: GNOME does not ask again
    assert seen[1]["actions"] == [["key", 0xFFE3, True], ["key", ord("c"), True], ["key", ord("c"), False], ["key", 0xFFE3, False]]


def test_a_click_goes_home_then_out_and_checks_the_screen():
    seen = []
    assert L.click("100,200", "double", runner=fake(seen=seen), size=(1920, 1080)) == "Double-clicked at 100,200."
    acts = seen[0]["actions"]
    assert acts[0][0] == "move" and acts[0][1] < 0 and acts[2] == ["move", 100, 200]
    assert [a for a in acts if a[0] == "button"] == [["button", 0x110, True], ["button", 0x110, False]] * 2
    with pytest.raises(ValueError):
        L.click("5000,10", runner=fake(), size=(1920, 1080))


def test_a_refusal_is_said():
    with pytest.raises(RuntimeError, match="did not run it: Start: refused"):
        L.type_text("x", runner=fake({"ok": False, "error": "Start: refused by the portal or the human (code 1)"}))


def test_the_desktop_tool_uses_it_off_windows(monkeypatch):
    from syrax import wininput

    monkeypatch.setattr(desktop, "WINDOWS", False)
    assert desktop._hands_module() is L
    monkeypatch.setattr(desktop, "WINDOWS", True)
    assert desktop._hands_module() is wininput


def test_tests_never_reach_the_real_portal():
    assert os.environ.get("SYRAX_NO_REAL_INPUT") == "1"
    with pytest.raises(RuntimeError, match="real keyboard and mouse input is off"):
        L.hotkey("ctrl+c")  # no runner: this would be the real portal
    with pytest.raises(RuntimeError, match="off here"):
        L.dark_mode("on")  # nor the real theme
