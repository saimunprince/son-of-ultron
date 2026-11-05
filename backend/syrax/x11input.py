"""Keyboard, mouse and windows on a Linux X11 desktop (KDE, Xfce, Cinnamon, MATE, GNOME on Xorg...), through xdotool
and wmctrl, which most distributions package. GNOME on Wayland uses its RemoteDesktop portal instead (linuxinput.py);
Wayland lets no program list or move other windows, X11 does.

The owner (2026-11-05): SYRAX should run right on any Linux. Same functions and answers as linuxinput and wininput, so
the desktop tool picks the backend for the session and says the same things. `runner` (tests) takes the argv and
returns (exit code, stdout); without it, SYRAX_NO_REAL_INPUT=1 (the tests' conftest) never touches the real desktop.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Callable, List, Optional, Tuple

MAX_TYPE = 2000
BUTTONS = {"left": "1", "middle": "2", "right": "3"}
# the names people and brains use -> xdotool's key names
KEY_NAMES = {
    "ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt", "win": "super", "super": "super", "cmd": "super",
    "meta": "super", "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape", "tab": "Tab",
    "space": "space", "backspace": "BackSpace", "delete": "Delete", "del": "Delete", "insert": "Insert",
    "home": "Home", "end": "End", "pgup": "Prior", "pageup": "Prior", "pgdn": "Next", "pagedown": "Next",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right", "printscreen": "Print", "print": "Print",
}

Runner = Callable[[List[str]], Tuple[int, str]]


class Stopped(RuntimeError):
    """Kept for the desktop tool's error handling (wininput.Stopped's counterpart)."""


def available() -> bool:
    return shutil.which("xdotool") is not None


def _run(argv: List[str], runner: Optional[Runner] = None) -> str:
    if runner is not None:
        code, out = runner(argv)
    else:
        if os.getenv("SYRAX_NO_REAL_INPUT") == "1":
            raise RuntimeError("real keyboard and mouse input is off here (SYRAX_NO_REAL_INPUT=1)")
        if not shutil.which(argv[0]):
            raise RuntimeError(f"{argv[0]} is not installed (Debian/Ubuntu: sudo apt install {argv[0]})")
        env = dict(os.environ)
        env.setdefault("DISPLAY", ":0")
        r = subprocess.run(argv, capture_output=True, text=True, timeout=20, env=env)
        code, out = r.returncode, (r.stdout or "") + ("" if r.returncode == 0 else r.stderr or "")
    if code != 0:
        raise RuntimeError(f"{argv[0]} failed: {out.strip()[:200] or code}")
    return out


def key_name(part: str) -> str:
    p = part.strip()
    low = p.lower()
    if low in KEY_NAMES:
        return KEY_NAMES[low]
    if re.fullmatch(r"f([1-9]|1[0-2])", low):
        return low.upper()
    if len(p) == 1:
        return low
    raise ValueError(f"unknown key {part!r}")


def parse_hotkey(spec: str) -> str:
    parts = [p for p in str(spec or "").replace(" ", "").split("+") if p]
    if not parts:
        raise ValueError("hotkey needs keys joined by +, e.g. ctrl+c")
    return "+".join(key_name(p) for p in parts)


def type_text(text: str, runner: Optional[Runner] = None) -> str:
    text = str(text or "")
    if not text:
        raise ValueError("type_text needs the text in value")
    if len(text) > MAX_TYPE:
        raise ValueError(f"at most {MAX_TYPE} characters at once")
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            _run(["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", line], runner)
        if i < len(lines) - 1:
            _run(["xdotool", "key", "--clearmodifiers", "Return"], runner)
    return f"Typed {len(text)} characters into the focused window."


def hotkey(spec: str, runner: Optional[Runner] = None) -> str:
    _run(["xdotool", "key", "--clearmodifiers", parse_hotkey(spec)], runner)
    return f"Pressed {str(spec).strip().lower()}."


def click(where: str, how: str = "left", runner: Optional[Runner] = None, size: Optional[Tuple[int, int]] = None) -> str:
    try:
        x, y = (int(float(v)) for v in str(where or "").replace(" ", "").split(","))
    except ValueError:
        raise ValueError("click needs target 'x,y' in screen pixels")
    how = (how or "left").lower()
    which, times = ("left", 2) if how == "double" else (how, 1)
    if which not in BUTTONS:
        raise ValueError("value must be left, right, middle or double")
    w, h = size or screen(runner)
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError(f"{x},{y} is outside the screen ({w}x{h})")
    _run(["xdotool", "mousemove", str(x), str(y), "click", "--repeat", str(times), BUTTONS[which]], runner)
    return f"{'Double-clicked' if times == 2 else which.capitalize() + '-clicked'} at {x},{y}."


def screen(runner: Optional[Runner] = None) -> Tuple[int, int]:
    out = _run(["xdotool", "getdisplaygeometry"], runner)
    m = re.match(r"\s*(\d+)\s+(\d+)", out)
    if not m:
        raise RuntimeError("could not read the screen size (xdotool)")
    return int(m.group(1)), int(m.group(2))


def windows(runner: Optional[Runner] = None) -> List[Tuple[str, str]]:
    """[(id, title)] of the visible windows."""
    ids = _run(["xdotool", "search", "--onlyvisible", "--name", "."], runner).split()
    out = []
    for wid in ids[:60]:
        try:
            title = _run(["xdotool", "getwindowname", wid], runner).strip()
        except RuntimeError:
            continue
        if title:
            out.append((wid, title))
    return out


def _find(target: str, runner: Optional[Runner]) -> Tuple[str, str]:
    t = str(target or "").strip().lower()
    if not t:
        raise ValueError("window needs part of the window's title in target")
    hits = [(w, title) for w, title in windows(runner) if t in title.lower()]
    if not hits:
        raise ValueError(f"no open window's title contains {target!r}")
    return hits[0]


def window(value: str = "list", target: str = "", runner: Optional[Runner] = None) -> str:
    """list, focus, minimize, maximize, restore, left, right (target = part of the window title)."""
    v = (value or "list").lower()
    if v == "list":
        rows = windows(runner)
        return "Open windows:\n" + "\n".join(f"- {t}" for _, t in rows) if rows else "No open windows."
    wid, title = _find(target, runner)
    if v == "focus":
        _run(["xdotool", "windowactivate", "--sync", wid], runner)
    elif v == "minimize":
        _run(["xdotool", "windowminimize", wid], runner)
    elif v in ("maximize", "restore"):
        if shutil.which("wmctrl") or runner is not None:
            _run(["wmctrl", "-i", "-r", wid, "-b", f"{'add' if v == 'maximize' else 'remove'},maximized_vert,maximized_horz"], runner)
        else:
            _run(["xdotool", "windowactivate", "--sync", wid], runner)
            _run(["xdotool", "key", "--clearmodifiers", "super+Up" if v == "maximize" else "super+Down"], runner)
    elif v in ("left", "right"):
        _run(["xdotool", "windowactivate", "--sync", wid], runner)
        _run(["xdotool", "key", "--clearmodifiers", f"super+{v.capitalize()}"], runner)
    else:
        raise ValueError("value must be list, focus, minimize, maximize, restore, left or right")
    return f"{v.capitalize()}: '{title}'."


def dark_mode(value: str = "get", runner: Optional[Runner] = None) -> str:
    """The colour scheme where the desktop keeps it in gsettings (GNOME, Cinnamon, MATE, Budgie); KDE has no such key."""
    from syrax import linuxinput

    return linuxinput.dark_mode(value)
