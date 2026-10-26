"""Window control on Windows through user32 (no extra packages): list the
visible top-level windows, and focus / minimize / maximize / restore / snap
one of them by a piece of its title. Nothing closes a window: the desktop tool
never destroys work."""

from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes
from typing import List, Optional, Tuple

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
SPI_GETWORKAREA = 48
ACTIONS = ("list", "focus", "minimize", "maximize", "restore", "left", "right")

# SYRAX's own windows: its web UI (frontend/app/layout.tsx, title "SYRAX") in a browser tab or app window, and the
# Electron HUD (hud/main.js and hud/hud.html, title "SYRAX", electron.exe). Live 2026-10-25 every desktop action ran
# with "SYRAX - Google Chrome" in front: the owner types into that page, so SYRAX's keys and clicks landed in it.
OWN_PROCESSES = ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "chromium.exe",
                 "arc.exe", "electron.exe")
_OWN_TITLE = re.compile(r"^SYRAX(?:\s[-–—]\s.+)?$|\s[-–—]\sSYRAX$")
_BROWSER_TAIL = re.compile(r"\s[-–—]\s(?:Google Chrome|Microsoft.{0,2}Edge|Mozilla Firefox|Brave|Opera|Vivaldi|Chromium)$")


def is_own(w: Optional[dict]) -> bool:
    """Whether a window (foreground() / window_at()) is SYRAX's own: titled exactly "SYRAX", starting "SYRAX - " or
    ending " - SYRAX", in a browser or Electron process. When the program cannot be read, the title alone decides:
    "SYRAX", or "SYRAX - " with a browser's name at the end. Any other program (a "SYRAX" folder in Explorer,
    "SYRAX_STATUS.md - Visual Studio Code") is not SYRAX's own window."""
    if not w:
        return False
    title = " ".join(str(w.get("title") or "").split())
    process = str(w.get("process") or "").strip().lower()
    if not _OWN_TITLE.search(title):
        return False
    if process:
        return process in OWN_PROCESSES
    return title == "SYRAX" or bool(_BROWSER_TAIL.search(title))


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


def foreground() -> Optional[dict]:
    """The window the human sees in front: its title and the program that owns it; None when there is none."""
    u = _user32()
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return None
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process = ""
    try:
        import psutil

        process = psutil.Process(pid.value).name()
    except Exception:
        pass
    return {"title": buf.value, "process": process, "pid": int(pid.value)}


GA_ROOT = 2
_typed = None


def _user32_typed():
    """user32 with handle-sized types for window_at; its own WinDLL, so the shared windll keeps its defaults."""
    global _typed
    if _typed is None:
        _user32()  # not Windows: OSError
        u = ctypes.WinDLL("user32")
        u.WindowFromPoint.argtypes = [wintypes.POINT]
        u.WindowFromPoint.restype = wintypes.HWND
        u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetAncestor.restype = wintypes.HWND
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        _typed = u
    return _typed


def window_at(x: int, y: int) -> Optional[dict]:
    """The top-level window at a point of the screen (the clicker's coordinates): its title, the program
    that owns it (read as foreground() reads it) and whether it is the window in front; None when there
    is none. It only reads: nothing is focused, moved or clicked."""
    u = _user32_typed()
    root = u.GetAncestor(u.WindowFromPoint(wintypes.POINT(int(x), int(y))), GA_ROOT)
    if not root:
        return None
    front = u.GetForegroundWindow()
    front = u.GetAncestor(front, GA_ROOT) if front else None
    n = u.GetWindowTextLengthW(root)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(root, buf, n + 1)
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(root, ctypes.byref(pid))
    process = ""
    try:
        import psutil

        process = psutil.Process(pid.value).name()
    except Exception:
        pass
    return {"title": buf.value, "process": process, "front": bool(front) and front == root}


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
