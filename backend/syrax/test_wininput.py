"""SYRAX's hands on Windows (feature catalog: keyboard_mouse, dark_mode,
display_sleep). A fake backend records every key, click and registry write,
so these tests never touch the real keyboard, mouse, theme or screen."""

import asyncio

import pytest

from syrax import permissions, wininput
from syrax.desktop import DesktopControl


class Fake:
    def __init__(self, cursor=(500, 400), light=1):
        self.log, self.pos, self.light = [], cursor, light

    def key(self, vk, up):
        self.log.append(("key", vk, up))

    def char(self, ch):
        self.log.append(("char", ch))

    def cursor(self):
        return self.pos

    def screen(self):
        return 1920, 1080

    def move(self, x, y):
        self.log.append(("move", x, y))

    def button(self, which, up):
        self.log.append(("button", which, up))

    def theme(self):
        return self.light, self.light

    def set_theme(self, light):
        self.log.append(("theme", light))
        self.light = light

    def monitor_off(self):
        self.log.append(("monitor_off",))


def test_typing_sends_each_character_and_enter_for_new_lines():
    b = Fake()
    assert wininput.type_text("hi\nবা", b, pause=0) == "Typed 5 characters into the focused window."
    assert b.log == [("char", "h"), ("char", "i"), ("key", 0x0D, False), ("key", 0x0D, True), ("char", "ব"), ("char", "া")]
    with pytest.raises(ValueError):
        wininput.type_text("", b)
    with pytest.raises(ValueError):
        wininput.type_text("x" * (wininput.MAX_TYPE + 1), b)


def test_the_top_left_corner_stops_the_hands():
    b = Fake(cursor=(0, 0))
    for call in (lambda: wininput.type_text("hello", b, pause=0), lambda: wininput.hotkey("ctrl+c", b),
                 lambda: wininput.click("100,100", "left", b)):
        with pytest.raises(wininput.Stopped):
            call()
    assert b.log == []  # nothing was typed, pressed or clicked

    class Moving(Fake):  # the human moves the mouse to the corner while SYRAX types
        def char(self, ch):
            super().char(ch)
            if len(self.log) == 20:
                self.pos = (1, 2)

    m = Moving()
    with pytest.raises(wininput.Stopped):
        wininput.type_text("x" * 100, m, pause=0)
    assert len(m.log) == 20


def test_hotkeys_press_in_order_and_release_in_reverse():
    b = Fake()
    assert wininput.hotkey("Ctrl + Shift + S", b) == "Pressed ctrl + shift + s."
    assert b.log == [("key", 0x11, False), ("key", 0x10, False), ("key", 0x53, False),
                     ("key", 0x53, True), ("key", 0x10, True), ("key", 0x11, True)]
    for bad in ("", "ctrl+nope", "a+b+c+d+e"):
        with pytest.raises(ValueError):
            wininput.parse_hotkey(bad)


def test_clicks_land_where_asked_and_never_off_screen():
    b = Fake()
    assert wininput.click("100, 200", "double", b) == "Double-clicked at 100,200."
    assert b.log == [("move", 100, 200), ("button", "left", False), ("button", "left", True),
                     ("button", "left", False), ("button", "left", True)]
    for where, how in (("5000,10", "left"), ("x", "left"), ("10,10", "sideways")):
        with pytest.raises(ValueError):
            wininput.click(where, how, Fake())


def test_dark_mode_reports_the_old_mode_and_display_off():
    b = Fake(light=1)
    assert wininput.dark_mode("get", b) == "Windows is in light mode."
    assert wininput.dark_mode("on", b) == "Windows switched from light to dark mode (to undo, switch it back to light)."
    assert b.log == [("theme", 0)]
    with pytest.raises(ValueError):
        wininput.dark_mode("purple", b)
    assert wininput.display_off(b).startswith("The display is off") and b.log[-1] == ("monitor_off",)


def test_the_desktop_tool_offers_them_at_system_level_only_to_a_conversation(monkeypatch):
    enum = DesktopControl().parameters["properties"]["action"]["enum"]
    assert {"type_text", "hotkey", "click", "dark_mode", "display_off"} <= set(enum)
    d = permissions.classify("desktop", {"action": "type_text", "value": "hello"})
    assert d.level == permissions.SYSTEM
    assert permissions.decide(d, "autonomous", "type hello").action == "refuse"
    assert permissions.decide(d, "conversation", "type hello").action == "allow"
    monkeypatch.setattr(wininput.sys, "platform", "linux")
    out = asyncio.run(DesktopControl().execute(action="hotkey", value="ctrl+c"))
    assert out.error and "Windows-only" in out.error
