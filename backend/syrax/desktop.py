"""SYRAX desktop control for the human's own Linux session.

One tool, many actions: open websites/files/apps in the human's desktop, volume,
media, screenshots, notifications, clipboard, file search, system info, lock.
Nothing destructive (no shutdown, no killing processes, no deleting files).
"""

from __future__ import annotations

import asyncio
import base64
import configparser
import glob
import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.config import config
from app.tool.base import BaseTool, ToolResult

APP_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    str(Path.home() / ".local/share/applications"),
    "/var/lib/snapd/desktop/applications",
    "/var/lib/flatpak/exports/share/applications",
    str(Path.home() / ".local/share/flatpak/exports/share/applications"),
]
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", ".next", "vendor"}


def session_env() -> Dict[str, str]:
    """Environment that reaches the graphical session even from a service."""
    env = dict(os.environ)
    uid = os.getuid()
    runtime = env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    if "WAYLAND_DISPLAY" not in env and os.path.exists(f"{runtime}/wayland-0"):
        env["WAYLAND_DISPLAY"] = "wayland-0"
    env.setdefault("DISPLAY", ":0")
    return env


async def _run(*args: str, timeout: float = 15, stdin: Optional[bytes] = None, detach: bool = False) -> tuple:
    if detach:
        await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL, env=session_env(), start_new_session=True,
        )
        return 0, "", ""
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=session_env(),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", "timed out"
    return proc.returncode, out.decode(errors="replace").strip(), err.decode(errors="replace").strip()


def installed_apps() -> List[dict]:
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


ALIASES = {
    "vs code": "visual studio code", "vscode": "visual studio code", "code": "visual studio code",
    "chrome": "google chrome", "google": "google chrome",
    "file manager": "files", "explorer": "files", "nautilus": "files",
    "whatsapp": "whatsapp web", "settings": "settings", "terminal": "terminal",
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


def _looks_like_url(t: str) -> bool:
    return bool(re.match(r"^(https?://|www\.)", t) or re.match(r"^[\w-]+(\.[\w-]+)+(/\S*)?$", t))


class DesktopControl(BaseTool):
    name: str = "desktop"
    description: str = (
        "Control the human's own computer (GNOME/Linux). Use this when they want something to happen "
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
            if app:
                return await self._do_launch_app(target=target)
            return ToolResult(error=f"Nothing to open: '{target}' is not a URL, an existing path or an installed app.")
        await _run("xdg-open", t, detach=True)
        return ToolResult(output=f"Opened {t} on the desktop.")

    async def _do_launch_app(self, target: str, **_) -> ToolResult:
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

    async def _do_media(self, value: str, **_) -> ToolResult:
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
        code, _, err = await _run("notify-send", "-a", "SYRAX", "SYRAX", text)
        return ToolResult(output="Notification shown.") if code == 0 else ToolResult(error=err or "notify-send failed")

    async def _do_clipboard_get(self, **_) -> ToolResult:
        env = session_env()
        cmd = ("wl-paste", "--no-newline") if env.get("WAYLAND_DISPLAY") and shutil.which("wl-paste") else ("xsel", "-ob")
        code, out, err = await _run(*cmd)
        if code != 0:
            return ToolResult(error=err or "clipboard is empty or unavailable")
        return ToolResult(output=out[:4000] or "(clipboard is empty)")

    async def _do_clipboard_set(self, value: str, **_) -> ToolResult:
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
        try:
            load = os.getloadavg()
            lines.append(f"CPU load: {load[0]:.2f} {load[1]:.2f} {load[2]:.2f} ({os.cpu_count()} cores)")
        except OSError:
            pass
        mem = {}
        try:
            for ln in Path("/proc/meminfo").read_text().splitlines():
                k, v = ln.split(":", 1)
                mem[k] = int(v.split()[0]) // 1024
            lines.append(f"RAM: {mem['MemTotal'] - mem['MemAvailable']} / {mem['MemTotal']} MB used")
        except Exception:
            pass
        du = shutil.disk_usage(str(Path.home()))
        lines.append(f"Disk (home): {du.used // 2**30} / {du.total // 2**30} GB used")
        for bat in glob.glob("/sys/class/power_supply/BAT*"):
            try:
                cap = Path(bat, "capacity").read_text().strip()
                st = Path(bat, "status").read_text().strip()
                lines.append(f"Battery: {cap}% ({st})")
            except OSError:
                pass
        try:
            up = float(Path("/proc/uptime").read_text().split()[0])
            lines.append(f"Uptime: {int(up // 3600)}h {int(up % 3600 // 60)}m")
        except Exception:
            pass
        return ToolResult(output="\n".join(lines))

    async def _do_lock_screen(self, **_) -> ToolResult:
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
