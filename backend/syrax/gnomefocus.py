"""The window in front on GNOME (Wayland), through SYRAX's own small shell extension (backend/gnome-extension).

GNOME 45+ answers no ordinary program which window has focus: org.gnome.Shell.Introspect.GetWindows is "not allowed"
and Shell.Eval is off. The extension exports one read-only D-Bus method, org.syrax.Focus.Focused, giving the title and
app class of the focused window. It is installed per user (no root) with `python -m syrax.gnomefocus install` and is
loaded by GNOME Shell at the next login. Without it, read() says None and the desktop tool works as before, without
the front-window checks. EVOLUTION_PLAN wave 3 (directions 226 application-state awareness, 227 action verification)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

UUID = "syrax-focus@son-of-ultron"
SOURCE = Path(__file__).resolve().parents[1] / "gnome-extension" / UUID
TARGET = Path.home() / ".local" / "share" / "gnome-shell" / "extensions" / UUID
CALL = ["gdbus", "call", "--session", "--dest", "org.syrax.Focus", "--object-path", "/org/syrax/Focus",
        "--method", "org.syrax.Focus.Focused", "--timeout", "2"]


def read(runner: Optional[Callable[[], str]] = None) -> Optional[dict]:
    """{"title", "wm_class"} of the focused window, {} when nothing has focus, None when it cannot be read (the
    extension is not loaded, not GNOME). `runner` (tests) returns gdbus's output."""
    try:
        if runner is None:
            r = subprocess.run(CALL, capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                return None
            raw = r.stdout
        else:
            raw = runner()
    except (OSError, subprocess.SubprocessError):
        return None
    raw = raw.strip()
    if not (raw.startswith("('") and raw.endswith("',)")):
        return None
    # the extension sends ASCII JSON (\uXXXX for the rest); gdbus's text form escapes only \ and '
    text = raw[2:-3].replace("\\\\", "\x00").replace("\\'", "'").replace("\x00", "\\")
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if data is None:
        return {}
    return {"title": str(data.get("title") or ""), "wm_class": str(data.get("wm_class") or "")}


def install() -> str:
    """Copy the extension into this user's GNOME extensions and enable it; it loads at the next login."""
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET)
    r = subprocess.run(["gsettings", "get", "org.gnome.shell", "enabled-extensions"], capture_output=True, text=True)
    current = r.stdout.strip()
    if UUID not in current:
        items = [] if current in ("@as []", "[]", "") else [x.strip(" '") for x in current.strip("[]").split(",") if x.strip()]
        items.append(UUID)
        subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions", str(items)], check=True)
    return f"installed {UUID} in {TARGET}; it starts at the next login"


if __name__ == "__main__":
    print(install() if sys.argv[1:] == ["install"] else json.dumps(read()))
