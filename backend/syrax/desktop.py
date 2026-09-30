"""SYRAX desktop control for the human's own session (GNOME/Linux or Windows).

One tool, many actions: open websites/files/apps in the human's desktop, volume,
media, screenshots, notifications, clipboard, file search, system info, lock.
Nothing destructive (no shutdown, no killing processes, no deleting files).

Linux talks to the session over the usual CLIs (xdg-open, gtk-launch, wpctl,
playerctl, notify-send, wl-copy, loginctl). Windows uses the shell
(os.startfile), Start Menu shortcuts, virtual media/volume keys, PIL for
screenshots and PowerShell for notifications and the clipboard.
"""

from __future__ import annotations

import asyncio
import base64
import configparser
import glob
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.config import config
from app.tool.base import BaseTool, ToolResult

from syrax import sysinfo

WINDOWS = sys.platform == "win32"

APP_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    str(Path.home() / ".local/share/applications"),
    "/var/lib/snapd/desktop/applications",
    "/var/lib/flatpak/exports/share/applications",
    str(Path.home() / ".local/share/flatpak/exports/share/applications"),
]
WIN_START_MENUS = [
    os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Microsoft", "Windows", "Start Menu", "Programs"),
    os.path.join(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")), "Microsoft", "Windows", "Start Menu", "Programs"),
]
WIN_SKIP_WORDS = ("uninstall", "readme", "release notes", "help", "documentation", "website")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", ".next", "vendor"}

# Windows virtual-key codes for the media/volume keys (keybd_event).
VK = {"mute": 0xAD, "vol_down": 0xAE, "vol_up": 0xAF, "next": 0xB0, "prev": 0xB1, "stop": 0xB2, "play_pause": 0xB3}


def session_env() -> Dict[str, str]:
    """Environment that reaches the graphical session even from a service."""
    env = dict(os.environ)
    if WINDOWS:
        return env
    uid = os.getuid()
    runtime = env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    if "WAYLAND_DISPLAY" not in env and os.path.exists(f"{runtime}/wayland-0"):
        env["WAYLAND_DISPLAY"] = "wayland-0"
    env.setdefault("DISPLAY", ":0")
    return env


async def _run(*args: str, timeout: float = 15, stdin: Optional[bytes] = None, detach: bool = False,
               extra_env: Optional[Dict[str, str]] = None) -> tuple:
    env = session_env()
    if extra_env:
        env.update(extra_env)
    if detach:
        kw = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
        await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL, env=env, **kw,
        )
        return 0, "", ""
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env, **kw,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", "timed out"
    return proc.returncode, out.decode(errors="replace").strip(), err.decode(errors="replace").strip()


async def _powershell(script: str, timeout: float = 15, extra_env: Optional[Dict[str, str]] = None) -> tuple:
    prelude = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8; "
    return await _run("powershell", "-NoProfile", "-NonInteractive", "-Command", prelude + script, timeout=timeout, extra_env=extra_env)


def _press_keys(*names: str, times: int = 1) -> None:
    """Tap virtual keys in the human's session (Windows only)."""
    import ctypes
    user32 = ctypes.windll.user32
    for _ in range(times):
        for n in names:
            user32.keybd_event(VK[n], 0, 0, 0)
            user32.keybd_event(VK[n], 0, 2, 0)  # KEYEVENTF_KEYUP


def installed_apps() -> List[dict]:
    if WINDOWS:
        return _win_installed_apps()
    apps, seen = [], set()
    for d in APP_DIRS:
        for path in glob.glob(f"{d}/*.desktop"):
            desktop_id = os.path.basename(path)
            if desktop_id in seen:
                continue
            cp = configparser.RawConfigParser(strict=False, interpolation=None)
            try:
                cp.read(path, encoding="utf-8")
                e = cp["Desktop Entry"]
            except Exception:
                continue
            if e.get("NoDisplay", "false").lower() == "true" or e.get("Type", "Application") != "Application":
                continue
            seen.add(desktop_id)
            apps.append({
                "id": desktop_id,
                "name": e.get("Name", desktop_id),
                "generic": e.get("GenericName", ""),
                "keywords": e.get("Keywords", ""),
                "exec": e.get("Exec", "").split(" ")[0],
            })
    return apps


def _win_installed_apps() -> List[dict]:
    """Start Menu shortcuts (.lnk), which is what the Start search shows too."""
    apps, seen = [], set()
    for root in WIN_START_MENUS:
        for path in glob.glob(os.path.join(root, "**", "*.lnk"), recursive=True):
            name = Path(path).stem
            key = name.lower()
            if key in seen or any(w in key for w in WIN_SKIP_WORDS):
                continue
            seen.add(key)
            folder = Path(path).parent.name if Path(path).parent != Path(root) else ""
            apps.append({"id": path, "name": name, "generic": folder, "keywords": "", "exec": ""})
    return apps


ALIASES = {
    "vs code": "visual studio code", "vscode": "visual studio code", "code": "visual studio code",
    "chrome": "google chrome", "google": "google chrome",
    "file manager": "files", "explorer": "files", "nautilus": "files",
    "whatsapp": "whatsapp web", "settings": "settings", "terminal": "terminal",
}
# Windows: things the Start Menu has no shortcut for but every machine can run.
WIN_BUILTINS = {
    "files": "explorer.exe", "file manager": "explorer.exe", "explorer": "explorer.exe",
    "settings": "ms-settings:", "terminal": "wt.exe", "notepad": "notepad.exe", "calculator": "calc.exe",
    "calc": "calc.exe", "paint": "mspaint.exe", "task manager": "taskmgr.exe", "cmd": "cmd.exe",
    "powershell": "powershell.exe", "edge": "msedge.exe", "microsoft edge": "msedge.exe", "camera": "microsoft.windows.camera:",
}


def match_app(query: str, apps: Optional[List[dict]] = None) -> Optional[dict]:
    q = " ".join(query.lower().split())
    if not q:
        return None
    q = ALIASES.get(q, q)
    qwords = q.split()
    apps = apps if apps is not None else installed_apps()
    best, best_score = None, 0
    for a in apps:
        name = a["name"].lower()
        nwords = set(re.findall(r"[\w+]+", name))
        keywords = {k.strip().lower() for k in a["keywords"].split(";") if k.strip()}
        hay = f"{name} {a['generic'].lower()} {' '.join(keywords)} {a['id'].lower()} {os.path.basename(a['exec']).lower()}"
        if q == name:
            score = 100
        elif name.startswith(q):
            score = 80
        elif all(w in nwords for w in qwords):
            score = 70
        elif q in name:
            score = 60
        elif q.replace(" ", "") in keywords:
            score = 50
        elif q in hay or all(w in hay for w in qwords):
            score = 40
        else:
            continue
        # Android (Waydroid) and site-app shortcuts lose to real desktop apps
        if a["id"].startswith("waydroid.") and "android" not in q:
            score -= 45
        if score > best_score:
            best, best_score = a, score
    return best


def _win_builtin(query: str) -> Optional[str]:
    q = " ".join(query.lower().split())
    return WIN_BUILTINS.get(q) or WIN_BUILTINS.get(ALIASES.get(q, ""))


def _looks_like_url(t: str) -> bool:
    return bool(re.match(r"^(https?://|www\.)", t) or re.match(r"^[\w-]+(\.[\w-]+)+(/\S*)?$", t))


class DesktopControl(BaseTool):
    name: str = "desktop"
    description: str = (
        "Control the human's own computer (GNOME/Linux or Windows). Use this when they want something to happen "
        "on THEIR screen: open a website in their browser, open a file/folder/app, set volume, "
        "play/pause music, take a screenshot, show a notification, read/write the clipboard, find "
        "files, check battery/CPU/RAM/disk, lock the screen. (Use the browser_* tools only when YOU "
        "need to read or operate a web page.)"
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "open", "launch_app", "list_apps", "volume", "media", "screenshot",
                    "notify", "clipboard_get", "clipboard_set", "find_files", "system_info", "lock_screen",
                ],
            },
            "target": {"type": "string", "description": "open: URL, file or folder. launch_app/list_apps: app name. find_files: name pattern."},
            "value": {"type": "string", "description": "volume: 0-100, 'up', 'down', 'mute', 'unmute', 'get'. media: play, pause, toggle, next, previous, status. notify/clipboard_set: text."},
            "folder": {"type": "string", "description": "find_files: folder to search (default: home)."},
        },
        "required": ["action"],
    }

    async def execute(self, action: str, target: str = "", value: str = "", folder: str = "") -> ToolResult:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return ToolResult(error=f"Unknown desktop action '{action}'.")
        try:
            return await handler(target=(target or "").strip(), value=(value or "").strip(), folder=(folder or "").strip())
        except Exception as e:
            return ToolResult(error=f"desktop {action} failed: {e}")

    # ——— actions ———
    async def _do_open(self, target: str, **_) -> ToolResult:
        if not target:
            return ToolResult(error="open needs a target (URL, file or folder).")
        t = os.path.expanduser(target)
        if _looks_like_url(t) and not os.path.exists(t):
            if not t.startswith("http"):
                t = "https://" + t
        elif not os.path.exists(t):
            app = match_app(target)
            if app or (WINDOWS and _win_builtin(target)):
                return await self._do_launch_app(target=target)
            return ToolResult(error=f"Nothing to open: '{target}' is not a URL, an existing path or an installed app.")
        if WINDOWS:
            os.startfile(t)  # the shell's own "open" verb
        else:
            await _run("xdg-open", t, detach=True)
        return ToolResult(output=f"Opened {t} on the desktop.")

    async def _do_launch_app(self, target: str, **_) -> ToolResult:
        if WINDOWS:
            return await self._win_launch_app(target)
        app = match_app(target)
        if not app:
            return ToolResult(error=f"No installed app matches '{target}'. Try list_apps.")
        code, _, err = await _run("gtk-launch", app["id"].removesuffix(".desktop"), timeout=10)
        if code != 0:
            exe = shutil.which(app["exec"]) if app["exec"] else None
            if not exe:
                return ToolResult(error=f"Could not launch {app['name']}: {err or code}")
            await _run(exe, detach=True)
        return ToolResult(output=f"Launched {app['name']}.")

    async def _win_launch_app(self, target: str) -> ToolResult:
        builtin = _win_builtin(target)
        if builtin:
            os.startfile(builtin)
            return ToolResult(output=f"Launched {target}.")
        app = match_app(target)
        if app:
            os.startfile(app["id"])
            return ToolResult(output=f"Launched {app['name']}.")
        exe = shutil.which(target)
        if exe:
            await _run(exe, detach=True)
            return ToolResult(output=f"Launched {target}.")
        return ToolResult(error=f"No installed app matches '{target}'. Try list_apps.")

    async def _do_list_apps(self, target: str, **_) -> ToolResult:
        apps = installed_apps()
        if target:
            q = target.lower()
            apps = [a for a in apps if q in f"{a['name']} {a['generic']} {a['keywords']}".lower()]
        names = sorted({a["name"] for a in apps})
        return ToolResult(output=", ".join(names[:80]) or "No matching apps.")

    async def _do_volume(self, value: str, **_) -> ToolResult:
        sink = "@DEFAULT_AUDIO_SINK@"
        v = value.lower().rstrip("%") or "get"
        if WINDOWS:
            return await self._win_volume(v)
        if shutil.which("wpctl"):
            if v == "up":
                await _run("wpctl", "set-volume", "-l", "1.0", sink, "10%+")
            elif v == "down":
                await _run("wpctl", "set-volume", sink, "10%-")
            elif v in ("mute", "unmute"):
                await _run("wpctl", "set-mute", sink, "1" if v == "mute" else "0")
            elif v.isdigit():
                await _run("wpctl", "set-volume", sink, f"{min(100, int(v))}%")
            elif v != "get":
                return ToolResult(error="volume value must be 0-100, up, down, mute, unmute or get.")
            _, out, _ = await _run("wpctl", "get-volume", sink)
            m = re.search(r"([\d.]+)", out)
            level = f"{round(float(m.group(1)) * 100)}%" if m else out
            return ToolResult(output=f"Volume {level}{' (muted)' if 'MUTED' in out else ''}.")
        if shutil.which("amixer"):
            arg = {"up": "10%+", "down": "10%-", "mute": "mute", "unmute": "unmute"}.get(v, f"{v}%" if v.isdigit() else None)
            if arg:
                await _run("amixer", "-q", "set", "Master", arg)
            _, out, _ = await _run("amixer", "get", "Master")
            m = re.search(r"\[(\d+)%\]", out)
            return ToolResult(output=f"Volume {m.group(1)}%." if m else out[:200])
        return ToolResult(error="No volume control (wpctl/amixer) found.")

    async def _win_volume(self, v: str) -> ToolResult:
        # Volume keys move the master level 2 % per tap; that is all Windows
        # offers without an audio SDK, so an exact level is reached from zero.
        if v == "up":
            _press_keys("vol_up", times=5)
        elif v == "down":
            _press_keys("vol_down", times=5)
        elif v in ("mute", "unmute"):
            muted = self._win_muted()
            if muted is None or muted != (v == "mute"):
                _press_keys("mute")
        elif v.isdigit():
            _press_keys("vol_down", times=50)
            _press_keys("vol_up", times=round(min(100, int(v)) / 2))
        elif v != "get":
            return ToolResult(error="volume value must be 0-100, up, down, mute, unmute or get.")
        level = self._win_volume_level()
        if level is None:
            return ToolResult(output="Volume set." if v != "get" else "Volume level is not readable on this machine.")
        return ToolResult(output=f"Volume {level}%.")

    @staticmethod
    def _win_volume_level() -> Optional[int]:
        try:  # optional: pycaw gives the exact level when installed
            from pycaw.pycaw import AudioUtilities  # type: ignore
            vol = AudioUtilities.GetSpeakers().EndpointVolume
            return round(vol.GetMasterVolumeLevelScalar() * 100)
        except Exception:
            return None

    @staticmethod
    def _win_muted() -> Optional[bool]:
        try:
            from pycaw.pycaw import AudioUtilities  # type: ignore
            return bool(AudioUtilities.GetSpeakers().EndpointVolume.GetMute())
        except Exception:
            return None

    async def _do_media(self, value: str, **_) -> ToolResult:
        if WINDOWS:
            key = {"play": "play_pause", "pause": "play_pause", "toggle": "play_pause", "next": "next",
                   "previous": "prev", "prev": "prev", "stop": "stop"}.get(value.lower())
            if value.lower() in ("status", ""):
                return ToolResult(output="Media status is not readable on Windows; play, pause, toggle, next and previous work.")
            if not key:
                return ToolResult(error="media value must be play, pause, toggle, next, previous or status.")
            _press_keys(key)
            return ToolResult(output=f"Media {value.lower()} sent.")
        if not shutil.which("playerctl"):
            return ToolResult(error="playerctl is not installed.")
        cmd = {"play": "play", "pause": "pause", "toggle": "play-pause", "next": "next",
               "previous": "previous", "prev": "previous", "status": "status", "": "status"}.get(value.lower())
        if not cmd:
            return ToolResult(error="media value must be play, pause, toggle, next, previous or status.")
        code, out, err = await _run("playerctl", cmd)
        if code != 0:
            return ToolResult(error=err or "No media player is running.")
        if cmd == "status":
            _, meta, _ = await _run("playerctl", "metadata", "--format", "{{artist}} - {{title}}")
            return ToolResult(output=f"{out}: {meta}".strip(": "))
        return ToolResult(output=f"Media {cmd} sent.")

    async def _do_screenshot(self, **_) -> ToolResult:
        shots = Path(config.workspace_root) / "screenshots"
        shots.mkdir(parents=True, exist_ok=True)
        path = shots / f"screen-{time.strftime('%Y%m%d-%H%M%S')}.png"
        if WINDOWS:
            from PIL import ImageGrab
            await asyncio.to_thread(lambda: ImageGrab.grab(all_screens=True).save(path))
            data = base64.b64encode(path.read_bytes()).decode()
            return ToolResult(output=f"Screenshot saved to {path}", base64_image=data)
        attempts = []
        if shutil.which("gnome-screenshot"):
            attempts.append(("gnome-screenshot", "-f", str(path)))
        if shutil.which("grim"):
            attempts.append(("grim", str(path)))
        if shutil.which("scrot"):
            attempts.append(("scrot", "-o", str(path)))
        if shutil.which("import"):
            attempts.append(("import", "-window", "root", str(path)))
        for args in attempts:
            code, _, _ = await _run(*args, timeout=20)
            if code == 0 and path.exists() and path.stat().st_size > 0:
                data = base64.b64encode(path.read_bytes()).decode()
                return ToolResult(output=f"Screenshot saved to {path}", base64_image=data)
        return ToolResult(error="Could not take a screenshot (no working screenshot tool).")

    async def _do_notify(self, value: str, target: str = "", **_) -> ToolResult:
        text = value or target
        if not text:
            return ToolResult(error="notify needs text in value.")
        if WINDOWS:
            script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
                "$n.ShowBalloonTip(8000, 'SYRAX', $env:SYRAX_NOTIFY_TEXT, [System.Windows.Forms.ToolTipIcon]::None); "
                "Start-Sleep -Seconds 8; $n.Dispose()"
            )
            code, _, err = await _powershell(script, timeout=20, extra_env={"SYRAX_NOTIFY_TEXT": text[:250]})
            return ToolResult(output="Notification shown.") if code == 0 else ToolResult(error=err or "notification failed")
        code, _, err = await _run("notify-send", "-a", "SYRAX", "SYRAX", text)
        return ToolResult(output="Notification shown.") if code == 0 else ToolResult(error=err or "notify-send failed")

    async def _do_clipboard_get(self, **_) -> ToolResult:
        if WINDOWS:
            code, out, err = await _powershell("Get-Clipboard -Raw")
            if code != 0:
                return ToolResult(error=err or "clipboard is unavailable")
            return ToolResult(output=out[:4000] or "(clipboard is empty)")
        env = session_env()
        cmd = ("wl-paste", "--no-newline") if env.get("WAYLAND_DISPLAY") and shutil.which("wl-paste") else ("xsel", "-ob")
        code, out, err = await _run(*cmd)
        if code != 0:
            return ToolResult(error=err or "clipboard is empty or unavailable")
        return ToolResult(output=out[:4000] or "(clipboard is empty)")

    async def _do_clipboard_set(self, value: str, **_) -> ToolResult:
        if WINDOWS:
            code, _, err = await _powershell("Set-Clipboard -Value $env:SYRAX_CLIP", extra_env={"SYRAX_CLIP": value})
            return ToolResult(output="Copied to clipboard.") if code == 0 else ToolResult(error=err or "clipboard write failed")
        env = session_env()
        cmd = ("wl-copy",) if env.get("WAYLAND_DISPLAY") and shutil.which("wl-copy") else ("xsel", "-ib")
        code, _, err = await _run(*cmd, stdin=value.encode())
        return ToolResult(output="Copied to clipboard.") if code == 0 else ToolResult(error=err or "clipboard write failed")

    async def _do_find_files(self, target: str, folder: str = "", **_) -> ToolResult:
        if not target:
            return ToolResult(error="find_files needs a name pattern in target.")
        root = Path(os.path.expanduser(folder or "~")).resolve()
        if not root.is_dir():
            return ToolResult(error=f"Folder not found: {root}")
        found = await asyncio.to_thread(_find, root, target.lower(), 25, 8.0)
        return ToolResult(output="\n".join(found) if found else f"No files matching '{target}' under {root}.")

    async def _do_system_info(self, **_) -> ToolResult:
        lines = []
        load = await asyncio.to_thread(sysinfo.loadavg)
        if load:
            lines.append(f"CPU load: {load[0]:.2f} {load[1]:.2f} {load[2]:.2f} ({os.cpu_count()} cores)")
        mem = sysinfo.meminfo()
        if mem["total_mb"] and mem["available_mb"] is not None:
            lines.append(f"RAM: {mem['total_mb'] - mem['available_mb']} / {mem['total_mb']} MB used")
        du = shutil.disk_usage(str(Path.home()))
        lines.append(f"Disk (home): {du.used // 2**30} / {du.total // 2**30} GB used")
        bat = sysinfo.battery()
        if bat:
            lines.append(f"Battery: {bat['percent']}% ({bat['status']})")
        up = sysinfo.uptime_seconds()
        if up is not None:
            lines.append(f"Uptime: {int(up // 3600)}h {int(up % 3600 // 60)}m")
        return ToolResult(output="\n".join(lines))

    async def _do_lock_screen(self, **_) -> ToolResult:
        if WINDOWS:
            code, _, err = await _run("rundll32.exe", "user32.dll,LockWorkStation")
            return ToolResult(output="Screen locked.") if code == 0 else ToolResult(error=err or "lock failed")
        code, _, err = await _run("loginctl", "lock-session")
        return ToolResult(output="Screen locked.") if code == 0 else ToolResult(error=err or "lock failed")


def _find(root: Path, needle: str, limit: int, budget_s: float) -> List[str]:
    """Name search that skips junk folders and stops on a time budget."""
    out, deadline = [], time.monotonic() + budget_s
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in dirnames + filenames:
            if needle in name.lower():
                out.append(os.path.join(dirpath, name))
                if len(out) >= limit:
                    return out
        if time.monotonic() > deadline:
            out.append("(search stopped: time budget reached)")
            return out
    return out
