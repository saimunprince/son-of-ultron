"""Keyboard, mouse, theme and display on Windows, through user32 (no new package).

Used by the desktop tool for type_text, hotkey, click, dark_mode and
display_off. These are SYSTEM-level actions: a human conversation may use
them, SYRAX's own (autonomous) work may not (permissions.py).

Failsafe: while the mouse sits in the top-left corner of the screen, typing,
key presses and clicks stop. That is the human's way to take SYRAX's hands
off the machine at once.

From the feature catalog (2026-10-12); the idea came from the surveyed JARVIS
assistants, the code is SYRAX's own. Every call goes through a backend object,
so tests never touch the real keyboard, mouse or registry.
"""

from __future__ import annotations

import sys
import time
from typing import Any, List, Optional, Tuple

MAX_TYPE = 2000
FAILSAFE_PX = 3
VK = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "windows": 0x5B,
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "printscreen": 0x2C, "capslock": 0x14,
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
    **{chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
}
MODIFIERS = {0x11, 0x12, 0x10, 0x5B}
THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


class Stopped(RuntimeError):
    """The failsafe tripped: the mouse is in the top-left corner."""


def parse_hotkey(spec: str) -> List[int]:
    keys = [k.strip().lower() for k in str(spec or "").replace(" ", "").split("+") if k.strip()]
    if not keys:
        raise ValueError("hotkey needs keys, e.g. ctrl+c or alt+tab")
    unknown = [k for k in keys if k not in VK]
    if unknown:
        raise ValueError(f"unknown key(s): {', '.join(unknown)}")
    if len(keys) > 4:
        raise ValueError("at most 4 keys at once")
    return [VK[k] for k in keys]


class Win32:
    """The real backend (Windows only)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes, self.wintypes = ctypes, wintypes
        self.user32 = ctypes.windll.user32

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        self.KEYBDINPUT, self.MOUSEINPUT, self.INPUT = KEYBDINPUT, MOUSEINPUT, INPUT

    def _send(self, inp) -> None:
        self.user32.SendInput(1, self.ctypes.byref(inp), self.ctypes.sizeof(inp))

    def key(self, vk: int, up: bool) -> None:
        inp = self.INPUT(type=1)
        inp.u.ki = self.KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0x0002 if up else 0, time=0, dwExtraInfo=None)
        self._send(inp)

    def char(self, ch: str) -> None:
        for up in (False, True):  # KEYEVENTF_UNICODE, so any language types as itself
            inp = self.INPUT(type=1)
            inp.u.ki = self.KEYBDINPUT(wVk=0, wScan=ord(ch), dwFlags=0x0004 | (0x0002 if up else 0), time=0, dwExtraInfo=None)
            self._send(inp)

    def cursor(self) -> Tuple[int, int]:
        pt = self.wintypes.POINT()
        self.user32.GetCursorPos(self.ctypes.byref(pt))
        return pt.x, pt.y

    def screen(self) -> Tuple[int, int]:
        return self.user32.GetSystemMetrics(0), self.user32.GetSystemMetrics(1)

    def move(self, x: int, y: int) -> None:
        self.user32.SetCursorPos(int(x), int(y))

    def button(self, which: str, up: bool) -> None:
        flags = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}[which]
        inp = self.INPUT(type=0)
        inp.u.mi = self.MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flags[1] if up else flags[0], time=0, dwExtraInfo=None)
        self._send(inp)

    def theme(self) -> Tuple[int, int]:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY) as k:
            return int(winreg.QueryValueEx(k, "AppsUseLightTheme")[0]), int(winreg.QueryValueEx(k, "SystemUsesLightTheme")[0])

    def set_theme(self, light: int) -> None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY, 0, winreg.KEY_SET_VALUE) as k:
            for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(light))
        result = self.wintypes.DWORD()  # tell open windows to repaint in the new theme
        self.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0x0002, 2000, self.ctypes.byref(result))

    def monitor_off(self) -> None:
        self.user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)  # WM_SYSCOMMAND, SC_MONITORPOWER, off


def backend() -> Any:
    if sys.platform != "win32":
        raise RuntimeError("keyboard, mouse, theme and display control are Windows-only for now")
    return Win32()


def _guard(b: Any) -> None:
    x, y = b.cursor()
    if x <= FAILSAFE_PX and y <= FAILSAFE_PX:
        raise Stopped("stopped: the mouse is in the top-left corner (the failsafe); move it away to let SYRAX type or click")


def type_text(text: str, b: Any = None, pause: float = 0.004) -> str:
    text = str(text or "")
    if not text:
        raise ValueError("type_text needs the text in value")
    if len(text) > MAX_TYPE:
        raise ValueError(f"at most {MAX_TYPE} characters at once")
    b = b or backend()
    _guard(b)
    for i, ch in enumerate(text):
        if i and i % 20 == 0:
            _guard(b)
        if ch == "\n":
            b.key(VK["enter"], False)
            b.key(VK["enter"], True)
        else:
            b.char(ch)
        if pause:
            time.sleep(pause)
    return f"Typed {len(text)} characters into the focused window."


def hotkey(spec: str, b: Any = None) -> str:
    keys = parse_hotkey(spec)
    b = b or backend()
    _guard(b)
    for vk in keys:
        b.key(vk, False)
    for vk in reversed(keys):
        b.key(vk, True)
    return f"Pressed {spec.strip().lower()}."


def click(where: str, how: str = "left", b: Any = None) -> str:
    try:
        x, y = (int(float(v)) for v in str(where or "").replace(" ", "").split(","))
    except ValueError:
        raise ValueError("click needs target 'x,y' in screen pixels")
    how = (how or "left").lower()
    which, times = ("left", 2) if how == "double" else (how, 1)
    if which not in ("left", "right", "middle"):
        raise ValueError("value must be left, right, middle or double")
    b = b or backend()
    w, h = b.screen()
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError(f"{x},{y} is outside the screen ({w}x{h})")
    _guard(b)
    b.move(x, y)
    for _ in range(times):
        b.button(which, False)
        b.button(which, True)
    return f"{'Double-clicked' if times == 2 else which.capitalize() + '-clicked'} at {x},{y}."


def dark_mode(value: str = "get", b: Any = None) -> str:
    b = b or backend()
    apps, system = b.theme()
    was = "dark" if apps == 0 else "light"
    value = (value or "get").lower()
    if value == "get":
        return f"Windows is in {was} mode."
    if value not in ("on", "off", "dark", "light"):
        raise ValueError("value must be on, off or get")
    want_light = 0 if value in ("on", "dark") else 1
    b.set_theme(want_light)
    now = "dark" if want_light == 0 else "light"
    return f"Windows switched from {was} to {now} mode (to undo, switch it back to {was})."


def display_off(b: Any = None) -> str:
    b = b or backend()
    b.monitor_off()
    return "The display is off; moving the mouse or pressing a key turns it back on."
