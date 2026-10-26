"""SYRAX desktop control for the human's own session (GNOME/Linux or Windows).

One tool, many actions: open websites/files/apps in the human's desktop, volume,
media, screenshots, notifications, clipboard, file search, system info, lock.
Nothing destructive (no shutdown, no killing processes, no deleting files).

Linux talks to the session over the usual CLIs (xdg-open, gtk-launch, wpctl,
playerctl, notify-send, wl-copy, loginctl). Windows uses the shell
(os.startfile), Start Menu shortcuts, virtual media/volume keys, PIL for
screenshots and PowerShell for notifications and the clipboard. macOS uses
`open`, /Applications, osascript (volume, Music, notifications, lock),
screencapture and pbcopy/pbpaste.
"""

from __future__ import annotations

import asyncio
import base64
import configparser
import glob
import json
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
MACOS = sys.platform == "darwin"
MAC_APP_DIRS = ["/Applications", "/System/Applications", "/System/Applications/Utilities", str(Path.home() / "Applications")]

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


# Windows' own media sessions (Global System Media Transport Controls): which app plays what and whether it plays,
# read and driven through PowerShell's WinRT bridge, no package. Live 2026-10-25: "play some random music" opened a
# YouTube search page, "play it your self" pressed the play/pause key (a toggle: it pauses what plays) and said
# "Media play sent.", and the answers said "Media is playing" four times while the human said it was not.
# $env:SYRAX_MEDIA_CMD: "" reads only; play | pause | toggle | next | previous | stop act on the current session first.
MEDIA_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(5000) | Out-Null; $task.Result }
[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime] | Out-Null
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$cmd = $env:SYRAX_MEDIA_CMD
$cur = $mgr.GetCurrentSession()
$done = $null
if ($cur -and $cmd) {
  $op = switch ($cmd) { 'play' { $cur.TryPlayAsync() } 'pause' { $cur.TryPauseAsync() } 'toggle' { $cur.TryTogglePlayPauseAsync() } 'next' { $cur.TrySkipNextAsync() } 'previous' { $cur.TrySkipPreviousAsync() } 'stop' { $cur.TryStopAsync() } }
  $done = Await $op ([bool])
  Start-Sleep -Milliseconds 900
}
$out = @()
foreach ($x in $mgr.GetSessions()) {
  $p = Await ($x.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
  $out += [pscustomobject]@{ app = $x.SourceAppUserModelId; status = "$($x.GetPlaybackInfo().PlaybackStatus)"; title = $p.Title }
}
[pscustomobject]@{ current = $(if ($cur) { $cur.SourceAppUserModelId } else { $null }); done = $done; sessions = $out } | ConvertTo-Json -Depth 4 -Compress
"""
MEDIA_COMMANDS = {"play": "play", "pause": "pause", "toggle": "toggle", "next": "next", "previous": "previous", "prev": "previous",
                  "stop": "stop"}
# live 2026-10-26: asked what plays, the brain called media "get" first, the word volume and dark_mode take
MEDIA_READS = ("status", "", "get", "state", "now", "current", "info", "what")
MEDIA_KEYS = {"play": "play_pause", "pause": "play_pause", "toggle": "play_pause", "next": "next", "previous": "prev", "prev": "prev",
              "stop": "stop"}


def media_app(app_id: object) -> str:
    """A session's app as a person names it: "Chrome", "Spotify", "Microsoft.ZuneMusic" (the package, not its id)."""
    name = str(app_id or "").split("!")[0]
    name = re.sub(r"_[a-z0-9]{13}$", "", name)  # a store package's publisher hash
    name = re.sub(r"(?i)\.exe$", "", name)
    return name[:40] or "an app"


def media_report(data: dict) -> str:
    """Every media session Windows knows, as the tool's answer: "Playing: 'Sajde' in Chrome." (a title that looks
    private is not written down, presence.redact); "Playing: " opens a session that plays (agent.py PLAYING_READ)."""
    from syrax import presence

    sessions = [x for x in (data.get("sessions") or []) if isinstance(x, dict)]
    if not sessions:
        return "No media session is open: nothing is playing or paused in any app."
    parts = []
    for x in sessions:
        title = presence.redact(str(x.get("title") or "")) or "an untitled item"
        parts.append(f"{str(x.get('status') or 'Unknown')}: '{title}' in {media_app(x.get('app'))}")
    return "; ".join(parts) + "."


def front_window() -> Optional[str]:
    """"'Title' (Program.exe)" of the window in front; "" when nothing is; None when it cannot be read (or off Windows).
    A title that looks private is not written down (presence.redact)."""
    if not WINDOWS:
        return None
    try:
        from syrax import presence, winctl

        w = winctl.foreground()
    except Exception:
        return None
    if not w:
        return ""
    title = presence.redact(str(w.get("title") or "")) or "an untitled window"
    return f"'{title}' ({w.get('process') or 'unknown program'})"


def in_front() -> str:
    """" In front now: 'Title' (Program.exe)." after a hands action, so the answer can say where the keys and clicks
    landed. Live 2026-10-25: "Typed 5 characters into the focused window.", Enter, and the answer "Message sent to
    bro bhi on Telegram." "" when unreadable."""
    w = front_window()
    if w is None:
        return ""
    return f" In front now: {w}." if w else " Nothing is in front now."


def _press_keys(*names: str, times: int = 1) -> None:
    """Tap virtual keys in the human's session (Windows only)."""
    import ctypes
    user32 = ctypes.windll.user32
    for _ in range(times):
        for n in names:
            user32.keybd_event(VK[n], 0, 0, 0)
            user32.keybd_event(VK[n], 0, 2, 0)  # KEYEVENTF_KEYUP


async def _osascript(*lines: str, timeout: float = 15) -> tuple:
    args: List[str] = []
    for ln in lines:
        args += ["-e", ln]
    return await _run("osascript", *args, timeout=timeout)


def _as_str(text: str) -> str:
    """Quote text for AppleScript."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _mac_installed_apps() -> List[dict]:
    apps, seen = [], set()
    for d in MAC_APP_DIRS:
        for path in glob.glob(os.path.join(d, "*.app")):
            name = Path(path).stem
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            apps.append({"id": path, "name": name, "generic": "", "keywords": "", "exec": ""})
    return apps


def installed_apps() -> List[dict]:
    if WINDOWS:
        return _win_installed_apps()
    if MACOS:
        return _mac_installed_apps()
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
    """Start Menu shortcuts (.lnk), which is what the Start search shows too, then the Start apps that have no
    shortcut on disk (Microsoft Store apps, _win_start_apps)."""
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
    for a in _win_start_apps():
        key = a["name"].lower()
        if key in seen or any(w in key for w in WIN_SKIP_WORDS):
            continue
        seen.add(key)
        apps.append(a)
    return apps


APPS_FOLDER = "shell:AppsFolder\\"
START_APPS_TTL_S = 600.0
_start_apps: Dict[str, object] = {"at": float("-inf"), "apps": []}  # never read yet


def _win_start_apps(now: Optional[float] = None) -> List[dict]:
    """The Start apps Windows lists that are not a shortcut file: Microsoft Store apps (WhatsApp, Spotify or Netflix
    from the Store), from Get-StartApps, launched through shell:AppsFolder\\<AppID>. Live 2026-10-25: Prince asked for
    WhatsApp, launch_app found no shortcut, and SYRAX answered that WhatsApp was not installed; it was
    (5319275A.WhatsAppDesktop). An AppID that is a path is a shortcut the .lnk scan has, or a document. Read once every
    START_APPS_TTL_S; nothing when PowerShell does not answer."""
    now = time.time() if now is None else now
    if now - float(_start_apps["at"]) < START_APPS_TTL_S:
        return list(_start_apps["apps"])  # type: ignore[arg-type]
    apps: List[dict] = []
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                            "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
                           capture_output=True, timeout=20)
        rows = json.loads(p.stdout.decode("utf-8", errors="replace").strip() or "[]")
        for r in [rows] if isinstance(rows, dict) else rows:
            name, appid = str(r.get("Name") or "").strip(), str(r.get("AppID") or "").strip()
            if not name or not appid or "\\" in appid or "/" in appid or re.search(r"(?i)\.(exe|lnk|url|chm|txt|pdf|html?|msc)$", appid):
                continue
            apps.append({"id": APPS_FOLDER + appid, "name": name, "generic": "", "keywords": "", "exec": ""})
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        apps = []
    _start_apps.update(at=now, apps=apps)
    return list(apps)


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
    apps = apps if apps is not None else installed_apps()
    if ALIASES.get(q, q) != q:
        # an alias first ("whatsapp" is "whatsapp web" where the web app is installed), then the words as said:
        # live 2026-10-25, Windows has the WhatsApp Store app and no "WhatsApp Web"
        return _match_app(ALIASES[q], apps) or _match_app(q, apps)
    return _match_app(q, apps)


def _match_app(q: str, apps: List[dict]) -> Optional[dict]:
    qwords = q.split()
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
        "Control the human's own computer (GNOME/Linux, Windows or macOS). Use this when they want something to happen "
        "on THEIR screen: open a website in their browser, open a file/folder/app, set volume, "
        "play/pause music, take a screenshot, show a notification, read/write the clipboard, find "
        "files, check battery/CPU/RAM/disk, lock the screen. Whether an app is installed: list_apps with its name "
        "(on Windows Microsoft Store apps such as WhatsApp included), never a file search. On Windows also: type text into the focused window "
        "(type_text), press keys (hotkey, e.g. ctrl+c, alt+tab), click at screen pixels (click) or on what the screen shows by its words (click_text: a button, menu, tab, link or text; find_text only says where it is), switch dark mode "
        "(dark_mode) and turn the display off (display_off); the human stops typing and clicking by moving the "
        "mouse to the top-left corner. To delete the human's own files, use trash: it goes to the Recycle Bin and can be restored. camera takes one photo with the webcam when the human asks to be seen; you see the photo. (Use the browser_* tools only when YOU need to read or operate a web page.)"
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "open", "launch_app", "list_apps", "volume", "media", "screenshot",
                    "notify", "clipboard_get", "clipboard_set", "find_files", "system_info", "lock_screen", "window",
                    "type_text", "hotkey", "click", "click_text", "find_text", "dark_mode", "display_off", "trash", "camera",
                ],
            },
            "target": {"type": "string", "description": "open: URL, file or folder. launch_app/list_apps: app name (Store apps included). find_files: name pattern. click: 'x,y' screen pixels. click_text/find_text: the words on the control or the screen, e.g. Save. trash: the file or folder to move to the Recycle Bin."},
            "value": {"type": "string", "description": "volume: 0-100, 'up', 'down', 'mute', 'unmute', 'get'. media: status (what plays in which app), play, pause, toggle, next, previous, stop; each answer says what plays after it. notify/clipboard_set: text. window: list, focus, minimize, maximize, restore, left, right (target = part of the window title). type_text: the text. hotkey: keys joined by +, e.g. ctrl+shift+s. click: left, right, middle or double. dark_mode: on, off or get."},
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
        elif MACOS:
            await _run("open", t)
        else:
            await _run("xdg-open", t, detach=True)
        return ToolResult(output=f"Opened {t} on the desktop.")

    async def _do_launch_app(self, target: str, **_) -> ToolResult:
        if WINDOWS:
            return await self._win_launch_app(target)
        if MACOS:
            app = match_app(target)
            if app:
                code, _, err = await _run("open", "-a", app["id"])
                return ToolResult(output=f"Launched {app['name']}.") if code == 0 else ToolResult(error=err or "launch failed")
            code, _, err = await _run("open", "-a", target)  # let LaunchServices try the raw name
            return ToolResult(output=f"Launched {target}.") if code == 0 else ToolResult(error=f"No installed app matches '{target}'. Try list_apps.")
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
            if app["id"].startswith(APPS_FOLDER):  # a Store app: the shell starts it by its AppID
                await _run("explorer.exe", app["id"], detach=True)
            else:
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
        if MACOS:
            return await self._mac_volume(v)
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

    async def _mac_volume(self, v: str) -> ToolResult:
        if v in ("up", "down"):
            _, cur, _ = await _osascript("output volume of (get volume settings)")
            level = max(0, min(100, int(cur or 50) + (10 if v == "up" else -10)))
            await _osascript(f"set volume output volume {level}")
        elif v in ("mute", "unmute"):
            await _osascript(f"set volume {'with' if v == 'mute' else 'without'} output muted")
        elif v.isdigit():
            await _osascript(f"set volume output volume {min(100, int(v))}")
        elif v != "get":
            return ToolResult(error="volume value must be 0-100, up, down, mute, unmute or get.")
        _, out, _ = await _osascript("get volume settings")
        m = re.search(r"output volume:(\d+)", out)
        muted = "output muted:true" in out
        return ToolResult(output=f"Volume {m.group(1) if m else '?'}%{' (muted)' if muted else ''}.")

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

    async def _media_sessions(self, cmd: Optional[str] = None) -> dict:
        """{current, done, sessions: [{app, status, title}]} from Windows (MEDIA_PS); `cmd` acts on the current session
        first. RuntimeError when PowerShell gives no answer (an old Windows, a policy, a timeout)."""
        code, out, err = await _powershell(MEDIA_PS, timeout=25, extra_env={"SYRAX_MEDIA_CMD": cmd or ""})
        line = next((ln for ln in reversed((out or "").splitlines()) if ln.strip().startswith("{")), "")
        if code != 0 or not line:
            raise RuntimeError(((err or out or "").strip().splitlines() or [f"exit {code}"])[-1][:200])
        return json.loads(line)

    async def _do_media(self, value: str, **_) -> ToolResult:
        if WINDOWS:
            v = value.lower()
            if v in MEDIA_READS:
                v = "status"
            if v != "status" and v not in MEDIA_COMMANDS:
                return ToolResult(error="media value must be play, pause, toggle, next, previous, stop or status.")
            cmd = MEDIA_COMMANDS.get(v)
            try:
                data = await self._media_sessions(cmd)
            except (RuntimeError, ValueError, OSError) as e:
                if cmd is None:
                    return ToolResult(error=f"The playback state could not be read: {e}")
                _press_keys(MEDIA_KEYS[v])
                return ToolResult(output=f"Pressed the {MEDIA_KEYS[v].replace('_', '/')} key; whether anything plays could not be read ({e}).")
            if cmd is None:
                return ToolResult(output=media_report(data))
            if not data.get("current"):
                # no session to take the command: the media key is all there is (it may start the last player)
                _press_keys(MEDIA_KEYS[v])
                await asyncio.sleep(1.0)
                try:
                    after = media_report(await self._media_sessions(None))
                except (RuntimeError, ValueError, OSError) as e:
                    after = f"could not be read ({e})"
                return ToolResult(output=f"No media session was open to take {v}, so the {MEDIA_KEYS[v].replace('_', '/')} key was pressed. Now: {after}")
            app = media_app(data["current"])
            took = "taken by" if data.get("done") else "refused by"
            return ToolResult(output=f"{v.capitalize()} {took} {app}. Now: {media_report(data)}")
        if MACOS:  # the Music app; other players do not expose a scriptable transport
            cmd = {"play": "play", "pause": "pause", "toggle": "playpause", "next": "next track",
                   "previous": "previous track", "prev": "previous track", "status": None, "": None}
            if value.lower() not in cmd:
                return ToolResult(error="media value must be play, pause, toggle, next, previous or status.")
            if cmd[value.lower()] is None:
                _, out, err = await _osascript('tell application "Music" to (player state as string) & ": " & (artist of current track) & " - " & (name of current track)')
                return ToolResult(output=out) if out else ToolResult(error=err or "Music is not playing.")
            code, _, err = await _osascript(f'tell application "Music" to {cmd[value.lower()]}')
            return ToolResult(output=f"Media {value.lower()} sent to Music.") if code == 0 else ToolResult(error=err or "Music did not respond.")
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
        if MACOS:
            attempts.append(("screencapture", "-x", str(path)))
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
        if MACOS:
            code, _, err = await _osascript(f'display notification {_as_str(text[:250])} with title "SYRAX"')
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
        if MACOS:
            cmd = ("pbpaste",)
        else:
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
        if MACOS:
            cmd = ("pbcopy",)
        else:
            cmd = ("wl-copy",) if env.get("WAYLAND_DISPLAY") and shutil.which("wl-copy") else ("xsel", "-ib")
        code, _, err = await _run(*cmd, stdin=value.encode())
        return ToolResult(output="Copied to clipboard.") if code == 0 else ToolResult(error=err or "clipboard write failed")

    async def _do_find_files(self, target: str, folder: str = "", **_) -> ToolResult:
        # live 2026-10-14 (run #39): a brain asked for "whatever is in" a folder with find_files and no
        # pattern, and the call failed; with a folder named, an empty pattern lists that folder's files
        if not target and not folder:
            return ToolResult(error="find_files needs a name pattern in target, or a folder to list.")
        if not target:
            root = Path(os.path.expanduser(folder)).resolve()
            if not root.is_dir():
                return ToolResult(error=f"Folder not found: {root}")
            names = sorted(os.listdir(root))[:50]
            return ToolResult(output="\n".join(str(root / n) for n in names) if names else f"{root} is empty.")
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
        gpu_info = sysinfo.gpu()
        if gpu_info is not None:
            parts = [f"GPU: {gpu_info['name']}"]
            used = gpu_info.get("memory_used_mb")
            total = gpu_info.get("memory_total_mb")
            if used is not None and total is not None:
                parts.append(f", {used}/{total} MB")
            elif total is not None:
                parts.append(f", {total} MB")
            util = gpu_info.get("utilization_pct")
            if util is not None:
                parts.append(f", {util}%")
            lines.append("".join(parts))
        du = shutil.disk_usage(str(Path.home()))
        lines.append(f"Disk (home): {du.used // 2**30} / {du.total // 2**30} GB used")
        bat = sysinfo.battery()
        if bat:
            lines.append(f"Battery: {bat['percent']}% ({bat['status']})")
        up = sysinfo.uptime_seconds()
        if up is not None:
            lines.append(f"Uptime: {int(up // 3600)}h {int(up % 3600 // 60)}m")
        return ToolResult(output="\n".join(lines))

    async def _do_window(self, value: str, target: str = "", **_) -> ToolResult:
        if not WINDOWS:
            return ToolResult(error="window control is implemented for Windows; on Linux/macOS use launch_app/open")
        from syrax import winctl

        try:
            return ToolResult(output=await asyncio.to_thread(winctl.act, (value or "list").lower(), target))
        except (ValueError, OSError) as e:
            return ToolResult(error=str(e))

    async def _do_lock_screen(self, **_) -> ToolResult:
        if WINDOWS:
            code, _, err = await _run("rundll32.exe", "user32.dll,LockWorkStation")
            return ToolResult(output="Screen locked.") if code == 0 else ToolResult(error=err or "lock failed")
        if MACOS:  # Ctrl+Cmd+Q, the system lock shortcut
            code, _, err = await _osascript('tell application "System Events" to keystroke "q" using {command down, control down}')
            return ToolResult(output="Screen locked.") if code == 0 else ToolResult(error=err or "lock failed")
        code, _, err = await _run("loginctl", "lock-session")
        return ToolResult(output="Screen locked.") if code == 0 else ToolResult(error=err or "lock failed")

    # ——— hands (Windows, syrax/wininput.py): SYSTEM level, a human conversation only ———
    async def _hands(self, fn, *args) -> ToolResult:
        from syrax import wininput

        try:
            return ToolResult(output=await asyncio.to_thread(fn, *args))
        except (ValueError, RuntimeError, wininput.Stopped) as e:
            return ToolResult(error=str(e))

    async def _with_front(self, done: ToolResult, before: Optional[str] = None) -> ToolResult:
        """A hands action's result with the window in front after it (in_front), read a moment later. Given the
        window that was in front `before` keys went out, and it is not the one in front now, the answer names it:
        the keys went there. Live 2026-10-25: "close the notepadd application" minimized Notepad, then pressed
        alt+f4 at whatever came to the front, and answered that Notepad was closed."""
        if done.error:
            return done
        await asyncio.sleep(0.15)
        now = await asyncio.to_thread(front_window)
        went = f" The keys went to {before}." if before and now is not None and before != now else ""
        tail = "" if now is None else (f" In front now: {now}." if now else " Nothing is in front now.")  # as in_front
        return ToolResult(output=f"{done.output}{went}{tail}")

    async def _do_type_text(self, value: str, **_) -> ToolResult:
        from syrax import wininput

        before = await asyncio.to_thread(front_window)
        return await self._with_front(await self._hands(wininput.type_text, value), before)

    async def _do_hotkey(self, value: str, **_) -> ToolResult:
        from syrax import wininput

        before = await asyncio.to_thread(front_window)
        return await self._with_front(await self._hands(wininput.hotkey, value), before)

    async def _do_click(self, target: str, value: str = "", **_) -> ToolResult:
        from syrax import wininput

        return await self._with_front(await self._hands(wininput.click, target, value or "left"))

    async def _sight(self, target: str):
        from syrax import sight, wininput

        if not str(target or "").strip():
            raise ValueError("find_text and click_text need the words to look for in target, e.g. Save.")
        spot, seen = await asyncio.to_thread(sight.find, str(target).strip(), wininput.backend().screen())
        if spot is None and seen:  # a tie: each candidate names its window, so the brain can tell them apart
            try:
                seen = await asyncio.to_thread(sight.in_windows, seen)
            except Exception:
                pass
        return spot, seen

    async def _do_find_text(self, target: str = "", **_) -> ToolResult:
        """Where a control or some words are on the screen (sight.py); nothing is clicked."""
        try:
            spot, seen = await self._sight(target)
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
            return ToolResult(error=f"find_text: {e}")
        if not seen:
            return ToolResult(output=f'Nothing on the primary screen reads "{target}" (UI Automation and OCR).')
        head = f"Best: {spot.say()}." if spot else "Several places match equally well."
        return ToolResult(output=f"{head} Seen: " + "; ".join(s.say() for s in seen))

    async def _do_click_text(self, target: str = "", value: str = "", **_) -> ToolResult:
        """Click a control or words seen on the screen: UI Automation first, then OCR (sight.py)."""
        from syrax import wininput

        try:
            spot, seen = await self._sight(target)
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
            return ToolResult(error=f"click_text: {e}")
        if spot is None and not seen:
            return ToolResult(error=f'Nothing on the primary screen reads "{target}" (UI Automation and OCR); nothing was clicked. '
                                    "Take a screenshot to see what is there.")
        if spot is None:
            return ToolResult(error=f'"{target}" matches several places equally well; nothing was clicked. '
                                    "Choose one and use click with its x,y: " + "; ".join(s.say() for s in seen))
        done = await self._hands(wininput.click, f"{spot.x},{spot.y}", value or "left")
        if done.error:
            return done
        return ToolResult(output=f"{done.output} That is {spot.label}, found by {spot.how}.")

    async def _do_dark_mode(self, value: str, **_) -> ToolResult:
        from syrax import wininput

        return await self._hands(wininput.dark_mode, value or "get")

    async def _do_trash(self, target: str, **_) -> ToolResult:
        """Move a file or folder to the Recycle Bin (Send2Trash), so it can be restored."""
        if not target:
            return ToolResult(error="trash needs the file or folder in target.")
        p = Path(os.path.expanduser(target))
        if not p.exists():
            return ToolResult(error=f"Nothing to move: {target} does not exist.")
        from send2trash import send2trash

        await asyncio.to_thread(send2trash, str(p))
        if p.exists():
            return ToolResult(error=f"{p} is still there; the Recycle Bin did not take it.")
        return ToolResult(output=f"Moved {p} to the Recycle Bin; restore it from there if it was a mistake.")

    async def _do_camera(self, value: str = "", **_) -> ToolResult:
        """One photo from the webcam (camera.py), saved in the workspace, journaled and shown to the brain."""
        from syrax import camera
        from syrax.journal import get_journal

        try:
            index = int(value) if str(value or "").strip().isdigit() else 0
            png = await asyncio.to_thread(camera.capture, index)
        except Exception as e:
            return ToolResult(error=f"camera: {e}")
        shots = Path(config.workspace_root) / "camera"
        shots.mkdir(parents=True, exist_ok=True)
        path = shots / f"cam-{time.strftime('%Y%m%d-%H%M%S')}.png"
        path.write_bytes(png)
        try:
            await get_journal().record("camera.captured", {"path": str(path), "bytes": len(png)})
        except Exception:
            pass  # the photo is taken; the record is best effort, the UI still shows the tool call
        return ToolResult(output=f"Took one photo with the camera: {path}", base64_image=base64.b64encode(png).decode())

    async def _do_display_off(self, **_) -> ToolResult:
        from syrax import wininput

        return await self._hands(wininput.display_off)


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
