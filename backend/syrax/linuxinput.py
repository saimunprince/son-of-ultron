"""Keyboard, mouse and dark mode on Linux GNOME (Wayland), with no root and no new package.

Wayland lets no ordinary program inject input: xdotool reaches only X11 windows, and ydotool needs /dev/uinput (root).
GNOME's own way is the XDG RemoteDesktop portal: the first use shows GNOME's "allow remote interaction" dialog to the
human, and a restore token kept in backend/config lets later uses start without asking. The portal is driven by
_portal_input.py under the system python3 (it has PyGObject; SYRAX's venv has no D-Bus library).

Same calls as wininput (type_text, hotkey, click, dark_mode) so the desktop tool picks one by platform. SYSTEM level:
a human conversation may use them, SYRAX's own work may not (permissions.py). Unlike Windows there is no top-left
failsafe: Wayland does not let a program read where the pointer is. The emergency stop and the human-only level
remain. EVOLUTION_PLAN wave 3 (directions 208, 221, 226, 227)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from syrax.journal import BACKEND_ROOT

HELPER = Path(__file__).with_name("_portal_input.py")
SYSTEM_PY = os.getenv("SYRAX_SYSTEM_PYTHON", "/usr/bin/python3")
TOKEN_FILE = BACKEND_ROOT / "config" / "portal.token"
MAX_TYPE = 2000
HELPER_TIMEOUT_S = 120
BUTTONS = {"left": 0x110, "right": 0x111, "middle": 0x112}  # linux/input-event-codes.h BTN_*
KEYSYMS = {
    "ctrl": 0xFFE3, "control": 0xFFE3, "alt": 0xFFE9, "shift": 0xFFE1, "super": 0xFFEB, "win": 0xFFEB, "windows": 0xFFEB,
    "enter": 0xFF0D, "return": 0xFF0D, "tab": 0xFF09, "esc": 0xFF1B, "escape": 0xFF1B, "space": 0x20,
    "backspace": 0xFF08, "delete": 0xFFFF, "del": 0xFFFF, "insert": 0xFF63, "home": 0xFF50, "end": 0xFF57,
    "pageup": 0xFF55, "pagedown": 0xFF56, "left": 0xFF51, "up": 0xFF52, "right": 0xFF53, "down": 0xFF54,
    "printscreen": 0xFF61, "capslock": 0xFFE5,
    **{f"f{n}": 0xFFBE + n - 1 for n in range(1, 13)},
}


class Stopped(RuntimeError):
    """Kept for the desktop tool's error handling (wininput.Stopped's counterpart)."""


def keysym(ch: str) -> int:
    """X keysym of one character: Latin-1 maps to itself, every other character to 0x01000000 + its code point."""
    c = ord(ch)
    if ch == "\n":
        return KEYSYMS["enter"]
    if ch == "\t":
        return KEYSYMS["tab"]
    return c if 0x20 <= c <= 0xFF else 0x01000000 + c


def parse_hotkey(spec: str) -> List[int]:
    names = [p.strip().lower() for p in re.split(r"[+\s]+", str(spec or "")) if p.strip()]
    if not names:
        raise ValueError("hotkey needs keys in value, e.g. ctrl+c")
    out = []
    for n in names:
        if n in KEYSYMS:
            out.append(KEYSYMS[n])
        elif len(n) == 1:
            out.append(keysym(n))
        else:
            raise ValueError(f"unknown key {n!r}")
    return out


def run(actions: List[list], runner: Optional[Callable[[str], str]] = None) -> None:
    """Run actions through the portal helper, keeping its restore token. `runner` (tests) takes the JSON request and
    returns the helper's JSON answer."""
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    request = json.dumps({"token": token, "actions": actions})
    if runner is None:
        if os.getenv("SYRAX_NO_REAL_INPUT") == "1":
            # tests (conftest.py) never reach the real keyboard and mouse: live 2026-10-30, a gate run of an old
            # test pressed a real ctrl+c through the portal once this backend existed
            raise RuntimeError("real keyboard and mouse input is off here (SYRAX_NO_REAL_INPUT=1)")
        if not Path(SYSTEM_PY).exists():
            raise RuntimeError(f"no {SYSTEM_PY} with PyGObject to reach GNOME's RemoteDesktop portal")
        r = subprocess.run([SYSTEM_PY, str(HELPER)], input=request, capture_output=True, text=True, timeout=HELPER_TIMEOUT_S)
        answer = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else json.dumps({"ok": False, "error": r.stderr[-200:]})
    else:
        answer = runner(request)
    out = json.loads(answer)
    if not out.get("ok"):
        raise RuntimeError(f"the desktop portal did not run it: {out.get('error')}")
    if out.get("token") and out["token"] != token:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(out["token"], encoding="utf-8")
        os.chmod(TOKEN_FILE, 0o600)


def screen() -> Tuple[int, int]:
    r = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=10)
    m = re.search(r"current (\d+) x (\d+)", r.stdout)
    if not m:
        raise RuntimeError("could not read the screen size (xrandr)")
    return int(m.group(1)), int(m.group(2))


def type_text(text: str, runner: Any = None) -> str:
    text = str(text or "")
    if not text:
        raise ValueError("type_text needs the text in value")
    if len(text) > MAX_TYPE:
        raise ValueError(f"at most {MAX_TYPE} characters at once")
    actions = []
    for ch in text:
        k = keysym(ch)
        actions += [["key", k, True], ["key", k, False]]
    run(actions, runner)
    return f"Typed {len(text)} characters into the focused window."


def hotkey(spec: str, runner: Any = None) -> str:
    keys = parse_hotkey(spec)
    run([["key", k, True] for k in keys] + [["key", k, False] for k in reversed(keys)], runner)
    return f"Pressed {str(spec).strip().lower()}."


def click(where: str, how: str = "left", runner: Any = None, size: Optional[Tuple[int, int]] = None) -> str:
    try:
        x, y = (int(float(v)) for v in str(where or "").replace(" ", "").split(","))
    except ValueError:
        raise ValueError("click needs target 'x,y' in screen pixels")
    how = (how or "left").lower()
    which, times = ("left", 2) if how == "double" else (how, 1)
    if which not in BUTTONS:
        raise ValueError("value must be left, right, middle or double")
    w, h = size or screen()
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError(f"{x},{y} is outside the screen ({w}x{h})")
    # the portal moves the pointer relatively without a screen stream: to the top-left corner first, then out to x,y
    actions = [["move", -4 * w, -4 * h], ["sleep", 0.05], ["move", x, y], ["sleep", 0.05]]
    for _ in range(times):
        actions += [["button", BUTTONS[which], True], ["button", BUTTONS[which], False]]
    run(actions, runner)
    return f"{'Double-clicked' if times == 2 else which.capitalize() + '-clicked'} at {x},{y}."


def dark_mode(value: str = "get", runner: Any = None) -> str:
    """GNOME's colour scheme through gsettings: get, on, off."""
    value = (value or "get").lower()
    key = ["org.gnome.desktop.interface", "color-scheme"]
    if value not in ("get", "on", "off"):
        raise ValueError("value must be get, on or off")
    r = subprocess.run(["gsettings", "get", *key], capture_output=True, text=True, timeout=10)
    was = "on" if "dark" in (r.stdout or "") else "off"
    if value == "get":
        return f"Dark mode is {was}."
    if os.getenv("SYRAX_NO_REAL_INPUT") == "1":
        raise RuntimeError("changing the real desktop is off here (SYRAX_NO_REAL_INPUT=1)")
    subprocess.run(["gsettings", "set", *key, "prefer-dark" if value == "on" else "default"], check=True, timeout=10)
    return f"Dark mode turned {value} (it was {was})."  # undo.py reads what it was
