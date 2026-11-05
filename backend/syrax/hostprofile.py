"""What computer SYRAX runs on, and which of its desktop actions work here.

The owner (2026-11-05): SYRAX should run right on any Linux, any Windows and other systems, and know its own system.
Before this SYRAX knew only `platform.platform()` and tried what this computer cannot do (window control on Wayland,
again and again). The profile is read once (and again on request): the OS and its version, the desktop and the
display server, the helper programs found, and for each desktop action whether it works here and why not. The agent
gets a one-line summary in every task; self_inspect shows the whole profile.

Every rule below mirrors the branch desktop.py takes on that system; a rule says "no" only where desktop.py has no way.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from typing import Dict, Optional, Tuple

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"

TOOLS = ("wl-copy", "wl-paste", "xsel", "xclip", "xdotool", "ydotool", "playerctl", "wpctl", "pactl", "amixer",
         "notify-send", "gnome-screenshot", "grim", "scrot", "spectacle", "import", "loginctl", "gtk-launch", "xdg-open",
         "gsettings", "gdbus", "ffmpeg", "ffprobe", "adb", "tesseract", "python3")

_cache: Optional[dict] = None


def _session_var(name: str) -> str:
    """A variable of the graphical session; a user service often lacks it, so ask systemd's user manager too."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        out = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in out.splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1]
    return ""


def _os_release() -> Dict[str, str]:
    try:
        text = open("/etc/os-release", encoding="utf-8").read()
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v.strip().strip('"')
    return out


def _system() -> Tuple[str, str]:
    """(OS family, name and version as the human knows it)."""
    if WINDOWS:
        rel, ver, _, _ = platform.win32_ver()
        build = int(ver.split(".")[-1]) if ver and ver.split(".")[-1].isdigit() else 0
        name = "Windows 11" if rel == "10" and build >= 22000 else f"Windows {rel}"
        return "Windows", f"{name} (build {ver})" if ver else name
    if MACOS:
        return "macOS", f"macOS {platform.mac_ver()[0]}"
    osr = _os_release()
    return "Linux", osr.get("PRETTY_NAME") or f"Linux {platform.release()}"


def _display() -> Tuple[str, str]:
    """(desktop, display server) on Linux; the OS's own on Windows and macOS."""
    if WINDOWS:
        return "Windows shell", "windows"
    if MACOS:
        return "Aqua", "quartz"
    desktop = (_session_var("XDG_CURRENT_DESKTOP") or _session_var("DESKTOP_SESSION") or "unknown").split(":")[-1]
    kind = _session_var("XDG_SESSION_TYPE").lower()
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if not kind:
        kind = "wayland" if _session_var("WAYLAND_DISPLAY") or os.path.exists(f"{runtime}/wayland-0") else \
               "x11" if _session_var("DISPLAY") else "none"
    return desktop, kind


def _gnome_portal_ok(tools: Dict[str, bool]) -> bool:
    """GNOME's RemoteDesktop portal (linuxinput.py) needs GNOME, gdbus and the system python3 with PyGObject."""
    if not tools.get("python3") or not tools.get("gdbus"):
        return False
    try:
        r = subprocess.run(["/usr/bin/python3", "-c", "import gi"], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _cameras() -> bool:
    if WINDOWS or MACOS:
        return True  # opencv asks the OS; there is no cheap way to count without opening one
    return any(n.startswith("video") for n in os.listdir("/dev")) if os.path.isdir("/dev") else False


def actions(family: str, desktop: str, server: str, tools: Dict[str, bool], portal: bool, camera: bool) -> Dict[str, str]:
    """For each desktop action: "yes" or "no: why", as desktop.py would do it on this system."""
    def need(ok: bool, why: str) -> str:
        return "yes" if ok else f"no: {why}"

    if family == "Windows":
        return {a: "yes" for a in ("open", "launch_app", "list_apps", "volume", "media", "screenshot", "notify",
                                   "clipboard", "window", "type_text", "hotkey", "click", "click_text", "find_text",
                                   "dark_mode", "display_off", "lock_screen", "trash")} | {
            "camera": "yes", "phone": need(tools.get("adb", False), "adb is not installed"),
            "view_video": need(tools.get("ffmpeg", False), "ffmpeg is not installed")}
    if family == "macOS":
        no_hands = "no: keyboard, mouse and window control are not built for macOS"
        return {"open": "yes", "launch_app": "yes", "list_apps": "yes", "volume": "yes", "media": "yes (Music)",
                "screenshot": "yes", "notify": "yes", "clipboard": "yes", "lock_screen": "yes", "trash": "yes",
                "window": no_hands, "type_text": no_hands, "hotkey": no_hands, "click": no_hands,
                "click_text": no_hands, "find_text": no_hands, "dark_mode": no_hands, "display_off": no_hands,
                "camera": "yes", "phone": need(tools.get("adb", False), "adb is not installed"),
                "view_video": need(tools.get("ffmpeg", False), "ffmpeg is not installed")}
    wayland = server == "wayland"
    gnome = "gnome" in desktop.lower()
    shot = any(tools.get(t) for t in ("gnome-screenshot", "grim", "scrot", "import")) or (gnome and portal)
    clip = (wayland and tools.get("wl-copy") and tools.get("wl-paste")) or tools.get("xsel")
    hands = gnome and portal
    hands_why = ("needs GNOME's RemoteDesktop portal (GNOME with the system python3 and PyGObject)" if not gnome
                 else "the system python3 lacks PyGObject (python3-gi) or gdbus is missing")
    return {
        "open": need(tools.get("xdg-open", False), "xdg-open is not installed"),
        "launch_app": "yes",
        "list_apps": "yes",
        "volume": need(tools.get("wpctl", False) or tools.get("amixer", False), "neither wpctl nor amixer is installed"),
        "media": need(tools.get("playerctl", False), "playerctl is not installed"),
        "screenshot": need(shot, "no screenshot program (gnome-screenshot, grim, scrot) and no GNOME portal"),
        "notify": need(tools.get("notify-send", False), "notify-send is not installed"),
        "clipboard": need(bool(clip), "needs wl-clipboard on Wayland or xsel on X11"),
        "lock_screen": need(tools.get("loginctl", False), "loginctl is not available"),
        "trash": "yes",
        "window": "no: window control is built for Windows only" + ("; Wayland lets no program list or move other "
                                                                     "windows" if wayland else ""),
        "type_text": need(hands, hands_why), "hotkey": need(hands, hands_why), "click": need(hands, hands_why),
        "dark_mode": need(hands, hands_why),
        "click_text": "no: reading controls on the screen is built for Windows only",
        "find_text": "no: reading controls on the screen is built for Windows only",
        "display_off": "no: built for Windows only",
        "camera": need(camera, "no camera device (/dev/video*)"),
        "phone": need(tools.get("adb", False), "adb is not installed"),
        "view_video": need(tools.get("ffmpeg", False) and tools.get("ffprobe", False), "ffmpeg is not installed"),
    }


def profile(refresh: bool = False) -> dict:
    """This computer, read once per process (refresh=True reads it again)."""
    global _cache
    if _cache is not None and not refresh:
        return _cache
    family, name = _system()
    desktop, server = _display()
    tools = {t: shutil.which(t) is not None for t in TOOLS}
    portal = family == "Linux" and "gnome" in desktop.lower() and _gnome_portal_ok(tools)
    _cache = {
        "os": family, "name": name, "kernel": platform.release(), "arch": platform.machine(),
        "desktop": desktop, "display": server, "tools": tools,
        "actions": actions(family, desktop, server, tools, portal, _cameras()),
    }
    return _cache


def summary(p: Optional[dict] = None) -> str:
    """One line for the agent: the system, and the desktop actions that do not work here."""
    p = p or profile()
    cannot = sorted(a for a, v in p["actions"].items() if v.startswith("no"))
    where = p["name"] + ("" if p["os"] != "Linux" else f", {p['desktop']} on {p['display'].capitalize()}")
    tail = f" Desktop actions that do not work here (do not try them): {', '.join(cannot)}." if cannot else ""
    return f"THIS COMPUTER: {where} ({p['arch']}).{tail}"
