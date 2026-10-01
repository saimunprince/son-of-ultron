"""Window control on Windows through user32 (no extra packages): list the
visible top-level windows, and focus / minimize / maximize / restore / snap
one of them by a piece of its title. Nothing closes a window: the desktop tool
never destroys work."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import List, Optional, Tuple

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
SPI_GETWORKAREA = 48
ACTIONS = ("list", "focus", "minimize", "maximize", "restore", "left", "right")


def _user32():
    if sys.platform != "win32":
        raise OSError("window control is implemented for Windows")
    return ctypes.windll.user32


def windows() -> List[Tuple[int, str]]:
    """(handle, title) of visible, titled top-level windows, in z-order."""
    u = _user32()
    out: List[Tuple[int, str]] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    dwm = ctypes.windll.dwmapi

    def cloaked(hwnd) -> bool:  # visible to Windows but hidden from the user (Settings, Input Experience)
        val = ctypes.c_int(0)
        return dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(val), ctypes.sizeof(val)) == 0 and val.value != 0

    def each(hwnd, _):
        if u.IsWindowVisible(hwnd) and not cloaked(hwnd):
            n = u.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, buf, n + 1)
                title = buf.value.strip()
                if title and title not in ("Program Manager",):
                    out.append((int(hwnd), title))
        return True

    u.EnumWindows(proc(each), 0)
    return out


def find(title_part: str, wins: Optional[List[Tuple[int, str]]] = None) -> Optional[Tuple[int, str]]:
    """The first window (top of z-order) whose title contains ``title_part``."""
    q = " ".join(title_part.lower().split())
    for hwnd, title in (wins if wins is not None else windows()):
        if q and q in title.lower():
            return hwnd, title
    return None


def act(action: str, title_part: str = "") -> str:
    if action not in ACTIONS:
        raise ValueError(f"window value must be one of {', '.join(ACTIONS)}")
    if action == "list":
        names = [t for _, t in windows()][:60]
        return "Open windows:\n" + "\n".join(f"- {t}" for t in names) if names else "No visible windows."
    if not title_part:
        raise ValueError(f"window {action} needs part of the window title in target")
    hit = find(title_part)
    if not hit:
        raise ValueError(f"no open window title contains {title_part!r}; try value=list")
    hwnd, title = hit
    u = _user32()
    if action == "minimize":
        u.ShowWindow(hwnd, SW_MINIMIZE)
    elif action == "maximize":
        u.ShowWindow(hwnd, SW_MAXIMIZE)
    elif action == "restore":
        u.ShowWindow(hwnd, SW_RESTORE)
    elif action == "focus":
        u.ShowWindow(hwnd, SW_RESTORE)
        u.SetForegroundWindow(hwnd)
    else:  # left / right half of the work area
        rect = wintypes.RECT()
        u.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        w, h = rect.right - rect.left, rect.bottom - rect.top
        x = rect.left if action == "left" else rect.left + w // 2
        u.ShowWindow(hwnd, SW_RESTORE)
        u.MoveWindow(hwnd, x, rect.top, w // 2, h, True)
    verb = {"left": "snapped left", "right": "snapped right", "focus": "focused"}.get(action, action + "d")
    return f"{title}: {verb}."
