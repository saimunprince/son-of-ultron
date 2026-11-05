"""2026-11-05: X11 desktops (KDE, Xfce, Cinnamon, MATE, GNOME on Xorg) type, press keys, click and control windows
through xdotool, the same answers as the GNOME portal and Windows backends. The runner stands in for the commands."""

import pytest

from syrax import hostprofile as H
from syrax import x11input as X


def recorder(outputs=None):
    calls = []

    def run(argv):
        calls.append(argv)
        for key, out in (outputs or {}).items():
            if key in " ".join(argv):
                return 0, out
        return 0, ""
    return run, calls


def test_keys_are_named_as_xdotool_knows_them():
    assert X.parse_hotkey("ctrl+shift+s") == "ctrl+shift+s"
    assert X.parse_hotkey("win+Enter") == "super+Return"
    assert X.parse_hotkey("alt+F4") == "alt+F4"
    with pytest.raises(ValueError):
        X.parse_hotkey("ctrl+banana")


def test_typing_presses_return_between_lines_and_clicks_land_on_screen():
    run, calls = recorder({"getdisplaygeometry": "1920 1080"})
    assert X.type_text("hi\nthere", run) == "Typed 8 characters into the focused window."
    assert calls == [["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", "hi"],
                     ["xdotool", "key", "--clearmodifiers", "Return"],
                     ["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", "there"]]
    assert X.click("100,200", "double", run) == "Double-clicked at 100,200."
    assert calls[-1] == ["xdotool", "mousemove", "100", "200", "click", "--repeat", "2", "1"]
    with pytest.raises(ValueError, match="outside the screen"):
        X.click("5000,10", "left", run)


def test_windows_are_listed_and_focused_by_part_of_their_title():
    run, calls = recorder({"search": "11 22", "getwindowname 11": "Notes - Kate", "getwindowname 22": "Firefox"})
    assert X.window("list", "", run) == "Open windows:\n- Notes - Kate\n- Firefox"
    assert X.window("focus", "kate", run) == "Focus: 'Notes - Kate'."
    assert calls[-1] == ["xdotool", "windowactivate", "--sync", "11"]
    with pytest.raises(ValueError, match="no open window"):
        X.window("focus", "slack", run)


def test_the_real_desktop_is_never_touched_in_tests():
    with pytest.raises(RuntimeError, match="SYRAX_NO_REAL_INPUT"):
        X.hotkey("ctrl+c")


def test_kde_on_x11_with_xdotool_has_hands_and_windows():
    tools = {t: False for t in H.TOOLS} | {"xdotool": True, "xclip": True, "pactl": True, "spectacle": True}
    a = H.actions("Linux", "KDE", "x11", tools, False, True)
    assert a["type_text"] == a["click"] == a["window"] == a["clipboard"] == a["volume"] == a["screenshot"] == "yes"
