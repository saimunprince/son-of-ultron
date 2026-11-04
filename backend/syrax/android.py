"""SYRAX on the human's Android phone, over adb (USB or Wireless debugging on the same WiFi).

Two halves:
- the link: pair (once, with the code the phone shows), connect, find the phone on the WiFi (mDNS), disconnect.
  The ANDROID panel in the HUD drives these; the last address is kept in config/android.json (not in git).
- the hands: the desktop tool's `phone` action (desktop.py) reads the screen (a picture and the list of what is on
  it) and taps, types, swipes, presses keys and opens apps or links, the way a human uses the phone.

Coordinates are always in the picture's pixels: the screenshot is scaled down for the brain, and a tap at "x,y" is
scaled back up. The phone's own apps, WhatsApp among them, are already signed in, so nothing here asks for a login.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from syrax.journal import BACKEND_ROOT

CONFIG = BACKEND_ROOT / "config" / "android.json"
PICTURE_HEIGHT = 1280  # the screenshot's height for the brain; the phone's own is often 2400

NO_ADB = "adb is not installed on this computer (Ubuntu: sudo apt install adb)."
NO_PHONE = ("No Android phone is connected. Connect it from the ANDROID panel (Wireless debugging on the same WiFi, "
            "or USB debugging with a cable).")

# what the human calls an app -> its package (a fallback when the name is not in the package list)
KNOWN_APPS = {
    "whatsapp": "com.whatsapp", "whatsapp business": "com.whatsapp.w4b", "chrome": "com.android.chrome",
    "youtube": "com.google.android.youtube", "gmail": "com.google.android.gm", "maps": "com.google.android.apps.maps",
    "messenger": "com.facebook.orca", "facebook": "com.facebook.katana", "instagram": "com.instagram.android",
    "telegram": "org.telegram.messenger", "camera": "android.media.action.STILL_IMAGE_CAMERA",
    "play store": "com.android.vending", "photos": "com.google.android.apps.photos", "phone": "com.google.android.dialer",
    "messages": "com.google.android.apps.messaging", "contacts": "com.google.android.contacts",
    "calculator": "com.google.android.calculator", "clock": "com.google.android.deskclock", "settings": "com.android.settings",
}
# phone packages that send messages: a tap or Enter in one of them may send (permissions.classify)
MESSAGING_PACKAGES = {
    "com.whatsapp": "WhatsApp", "com.whatsapp.w4b": "WhatsApp", "org.telegram.messenger": "Telegram",
    "com.facebook.orca": "Messenger", "com.discord": "Discord", "com.Slack": "Slack", "com.viber.voip": "Viber",
    "com.instagram.android": "Instagram", "org.thoughtcrime.securesms": "Signal", "com.skype.raider": "Skype",
    "com.google.android.apps.messaging": "Messages", "com.samsung.android.messaging": "Messages",
    "com.tencent.mm": "WeChat", "jp.naver.line.android": "LINE", "com.microsoft.teams": "Microsoft Teams",
}
KEYS = {
    "back": "KEYCODE_BACK", "home": "KEYCODE_HOME", "recents": "KEYCODE_APP_SWITCH", "enter": "KEYCODE_ENTER",
    "delete": "KEYCODE_DEL", "backspace": "KEYCODE_DEL", "tab": "KEYCODE_TAB", "search": "KEYCODE_SEARCH",
    "volume_up": "KEYCODE_VOLUME_UP", "volume_down": "KEYCODE_VOLUME_DOWN", "mute": "KEYCODE_VOLUME_MUTE",
    "play_pause": "KEYCODE_MEDIA_PLAY_PAUSE", "next": "KEYCODE_MEDIA_NEXT", "previous": "KEYCODE_MEDIA_PREVIOUS",
    "wake": "KEYCODE_WAKEUP", "sleep": "KEYCODE_SLEEP", "menu": "KEYCODE_MENU", "escape": "KEYCODE_ESCAPE",
}
ADDRESS = re.compile(r"^\s*([0-9a-zA-Z.\-:\[\]]+?):(\d{2,5})\s*$")

_scale: Dict[str, float] = {}  # serial -> phone pixels per picture pixel, from the last screenshot


class PhoneError(Exception):
    pass


# ——— running adb ———
async def adb(*args: str, timeout: float = 20, binary: bool = False) -> Tuple[int, object, str]:
    """(exit code, stdout, stderr) of one adb command; stdout is bytes when binary."""
    if not shutil.which("adb"):
        raise PhoneError(NO_ADB)
    proc = await asyncio.create_subprocess_exec(
        "adb", *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, b"" if binary else "", "timed out"
    return proc.returncode, out if binary else out.decode(errors="replace").strip(), err.decode(errors="replace").strip()


def parse_devices(text: str) -> List[dict]:
    """`adb devices -l` -> [{serial, state, model, wifi}]."""
    rows = []
    for line in (text or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or line.startswith("*"):
            continue
        info = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        serial = parts[0]
        rows.append({"serial": serial, "state": parts[1], "model": info.get("model", "").replace("_", " "),
                     "wifi": bool(ADDRESS.match(serial)) or "_adb-tls-connect" in serial})
    return rows


async def devices() -> List[dict]:
    code, out, err = await adb("devices", "-l", timeout=10)
    if code != 0:
        raise PhoneError(err or "adb devices failed")
    return parse_devices(out)


async def serial() -> str:
    """The phone to use: the one ready device (the saved one first when several are ready)."""
    ready = [d for d in await devices() if d["state"] == "device"]
    if not ready:
        saved = load().get("address")
        if saved:  # the phone was connected before: try once more (WiFi dropped, the core restarted)
            await adb("connect", saved, timeout=8)
            ready = [d for d in await devices() if d["state"] == "device"]
        if not ready:
            raise PhoneError(NO_PHONE)
    saved = load().get("address")
    return next((d["serial"] for d in ready if d["serial"] == saved), ready[0]["serial"])


async def shell(*args: str, timeout: float = 20) -> str:
    code, out, err = await adb("-s", await serial(), "shell", *args, timeout=timeout)
    if code != 0:
        raise PhoneError(err or out or f"adb shell {args[0] if args else ''} failed")
    return str(out)


# ——— the saved address ———
def load() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def save(**fields) -> None:
    data = {**load(), **fields}
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, indent=2) + "\n")


def address(host: str, port) -> str:
    host = str(host or "").strip()
    port = str(port or "").strip()
    if not host:
        raise PhoneError("The phone's IP address is missing.")
    joined = host if not port else f"{host}:{port}"
    if not ADDRESS.match(joined):
        raise PhoneError(f"'{joined}' is not an address like 192.168.1.5:37123.")
    return joined


# ——— the link (the ANDROID panel) ———
async def status() -> dict:
    if not shutil.which("adb"):
        return {"adb": False, "devices": [], "saved": load().get("address"), "message": NO_ADB}
    try:
        rows = await devices()
    except PhoneError as e:
        return {"adb": True, "devices": [], "saved": load().get("address"), "message": str(e)}
    return {"adb": True, "devices": rows, "saved": load().get("address"), "message": ""}


async def pair(host: str, port, code: str) -> str:
    """Pair once with Wireless debugging's "Pair device with pairing code" (its own port, not the connect port)."""
    code = re.sub(r"\s+", "", str(code or ""))
    if not re.fullmatch(r"\d{6}", code):
        raise PhoneError("The pairing code is the 6 digits the phone shows.")
    rc, out, err = await adb("pair", address(host, port), code, timeout=25)
    text = f"{out} {err}".strip()
    if rc != 0 or "Successfully paired" not in text:
        raise PhoneError(f"Pairing failed: {text or rc}")
    return "Paired. Now connect with the port under 'IP address & Port' on the Wireless debugging page."


async def connect(host: str, port) -> str:
    where = address(host, port)
    rc, out, err = await adb("connect", where, timeout=15)
    text = f"{out} {err}".strip()
    if rc != 0 or not re.search(r"\bconnected to\b", text) or "failed" in text.lower():
        raise PhoneError(f"Could not connect to {where}: {text or rc}")
    save(address=where)
    return f"Connected to {where}."


def parse_mdns(text: str) -> List[str]:
    """`adb mdns services` -> the addresses phones offer for connecting (_adb-tls-connect)."""
    found = []
    for line in (text or "").splitlines():
        if "_adb-tls-connect" in line:
            m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3}:\d{2,5})", line)
            if m and m.group(1) not in found:
                found.append(m.group(1))
    return found


async def discover() -> str:
    """Find a phone with Wireless debugging on, on this WiFi, and connect to it (its port changes every time)."""
    rc, out, err = await adb("mdns", "services", timeout=10)
    found = parse_mdns(out)
    if not found:
        raise PhoneError("No phone found on the WiFi. On the phone: Developer options > Wireless debugging on, "
                         "same WiFi as this computer. A phone never paired here needs pairing first.")
    problems = []
    for where in found:
        host, _, port = where.rpartition(":")
        try:
            return await connect(host, port)
        except PhoneError as e:
            problems.append(str(e))
    raise PhoneError("; ".join(problems))


async def disconnect() -> str:
    await adb("disconnect", timeout=10)
    return "Disconnected every phone on the WiFi (a USB cable stays connected until it is unplugged)."


# ——— the hands (desktop action `phone`) ———
async def front_app() -> str:
    """The package of the app in front on the phone, '' when unknown."""
    out = await shell("dumpsys", "window", timeout=10)
    return parse_front(out)


def parse_front(dumpsys: str) -> str:
    m = re.search(r"mCurrentFocus=Window\{[^ ]+ [^ ]+ ([\w.]+)/", dumpsys or "") or \
        re.search(r"mFocusedApp=.*? ([\w.]+)/", dumpsys or "")
    return m.group(1) if m else ""


def front_app_sync(timeout: float = 4) -> Optional[str]:
    """front_app for the permission gate (synchronous); None when no phone answers."""
    if not shutil.which("adb"):
        return None
    try:
        r = subprocess.run(["adb", "shell", "dumpsys", "window"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_front(r.stdout) if r.returncode == 0 else None


def messaging_package(package: str) -> Optional[str]:
    return MESSAGING_PACKAGES.get(package or "")


async def screenshot(folder: Path) -> Tuple[str, str]:
    """(saved path, base64 PNG scaled to PICTURE_HEIGHT); remembers the scale for taps."""
    s = await serial()
    rc, png, err = await adb("-s", s, "exec-out", "screencap", "-p", timeout=25, binary=True)
    if rc != 0 or not png:
        raise PhoneError(f"The phone's screen could not be read: {err or rc}")
    from PIL import Image

    img = Image.open(io.BytesIO(png))
    scale = max(1.0, img.height / PICTURE_HEIGHT)
    if scale > 1:
        img = img.resize((round(img.width / scale), round(img.height / scale)))
    _scale[s] = scale
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"phone-{time.strftime('%Y%m%d-%H%M%S')}.png"
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    path.write_bytes(buf.getvalue())
    return str(path), base64.b64encode(buf.getvalue()).decode()


def scale_of(s: str) -> float:
    return _scale.get(s, 1.0)


_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def parse_ui(xml_text: str, scale: float = 1.0, limit: int = 80) -> List[dict]:
    """uiautomator's dump -> what a human sees and can touch: [{label, kind, x, y, tap}] in the picture's pixels."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    rows = []
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        rid = (node.get("resource-id") or "").rpartition("/")[2]
        tap = node.get("clickable") == "true" or node.get("long-clickable") == "true"
        edit = "EditText" in (node.get("class") or "")
        label = text or desc or (rid if (tap or edit) else "")
        m = _BOUNDS.search(node.get("bounds") or "")
        if not label or not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        if x2 <= x1 or y2 <= y1:
            continue
        kind = "field" if edit else ("button" if tap else "text")
        rows.append({"label": label[:80], "kind": kind, "x": round((x1 + x2) / 2 / scale),
                     "y": round((y1 + y2) / 2 / scale), "tap": tap or edit, "id": rid})
        if len(rows) >= limit:
            break
    return rows


async def ui() -> List[dict]:
    s = await serial()
    await shell("uiautomator", "dump", "/sdcard/syrax-ui.xml", timeout=25)
    rc, out, err = await adb("-s", s, "exec-out", "cat", "/sdcard/syrax-ui.xml", timeout=15)
    if rc != 0:
        raise PhoneError(f"The screen's layout could not be read: {err or rc}")
    return parse_ui(str(out), scale_of(s))


def render_ui(rows: List[dict]) -> str:
    if not rows:
        return "Nothing readable on the phone's screen (a game or a video shows no layout); use phone screen."
    return "\n".join(f"- [{r['kind']}] {r['label']} at {r['x']},{r['y']}" for r in rows)


def find(rows: List[dict], words: str) -> Optional[dict]:
    """The element named by words: an exact label first, then one that contains them; touchable ones first."""
    w = words.strip().lower()
    if not w:
        return None
    exact = [r for r in rows if r["label"].lower() == w or r["id"].lower() == w]
    partial = [r for r in rows if w in r["label"].lower()]
    for hits in (exact, partial):
        if hits:
            return next((r for r in hits if r["tap"]), hits[0])
    return None


POINT = re.compile(r"^\s*(\d+)\s*,\s*(\d+)\s*$")


async def tap(target: str) -> str:
    s = await serial()
    m = POINT.match(target or "")
    if m:
        x, y = (int(v) for v in m.groups())
        what = f"{x},{y}"
    else:
        if not (target or "").strip():
            raise PhoneError("tap needs the words on what to tap (Send, Search) or 'x,y' in the picture's pixels.")
        hit = find(await ui(), target)
        if not hit:
            raise PhoneError(f"Nothing on the phone's screen reads '{target}'. Read it with phone ui or phone screen.")
        x, y, what = hit["x"], hit["y"], f"'{hit['label']}' at {hit['x']},{hit['y']}"
    k = scale_of(s)
    await shell("input", "tap", str(round(x * k)), str(round(y * k)))
    return f"Tapped {what} on the phone."


def escape_text(text: str) -> str:
    """Text for `adb shell input text`: spaces as %s, the device shell's special characters escaped."""
    out = []
    for ch in text:
        if ch == " ":
            out.append("%s")
        elif ch in "\\'\"`$&|;<>()*~#!?[]{}%^":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


async def type_text(text: str) -> str:
    if not text:
        raise PhoneError("type needs the text.")
    if any(ord(c) > 126 for c in text):
        raise PhoneError("adb types only plain English letters, digits and signs; Bangla or emoji cannot be typed. "
                         "Open a link with the text instead (whatsapp: https://wa.me/<number>?text=...).")
    lines = text.replace("\r", "").split("\n")
    for i, line in enumerate(lines):
        if line:
            await shell("input", "text", escape_text(line))
        if i < len(lines) - 1:
            await shell("input", "keyevent", "KEYCODE_ENTER")
    return f"Typed {len(text)} characters on the phone."


async def key(name: str) -> str:
    code = KEYS.get((name or "").strip().lower().replace(" ", "_"))
    if not code:
        raise PhoneError(f"Unknown key '{name}'. Keys: {', '.join(KEYS)}.")
    await shell("input", "keyevent", code)
    return f"Pressed {name} on the phone."


async def swipe(direction: str) -> str:
    s = await serial()
    d = (direction or "up").strip().lower()
    m = re.fullmatch(r"(\d+),(\d+),(\d+),(\d+)", d.replace(" ", ""))
    if m:
        k = scale_of(s)
        pts = [str(round(int(v) * k)) for v in m.groups()]
    else:
        size = await shell("wm", "size")
        sm = re.search(r"(\d+)x(\d+)\s*$", size)
        w, h = (int(sm.group(1)), int(sm.group(2))) if sm else (1080, 2400)
        moves = {"up": (w / 2, h * 0.75, w / 2, h * 0.25), "down": (w / 2, h * 0.25, w / 2, h * 0.75),
                 "left": (w * 0.85, h / 2, w * 0.15, h / 2), "right": (w * 0.15, h / 2, w * 0.85, h / 2)}
        if d not in moves:
            raise PhoneError("swipe takes up, down, left, right or 'x1,y1,x2,y2' in the picture's pixels.")
        pts = [str(round(v)) for v in moves[d]]
    await shell("input", "swipe", *pts, "300")
    return f"Swiped {d} on the phone."


async def packages() -> List[str]:
    out = await shell("pm", "list", "packages", "-3", timeout=20)
    system = await shell("pm", "list", "packages", "-s", timeout=20)
    return [line.partition(":")[2].strip() for line in f"{out}\n{system}".splitlines() if line.startswith("package:")]


def match_package(name: str, installed: List[str]) -> Optional[str]:
    n = name.strip().lower()
    if n in installed:
        return n
    known = KNOWN_APPS.get(n)
    if known and known in installed:
        return known
    squeezed = re.sub(r"[^a-z0-9]", "", n)
    hits = [p for p in installed if squeezed and squeezed in p.lower().replace("_", "")]
    return min(hits, key=len) if hits else None


async def open_app(target: str) -> str:
    t = (target or "").strip()
    if not t:
        raise PhoneError("open needs an app name or a link.")
    if re.match(r"^(https?://|tel:|mailto:|whatsapp://|geo:)", t, re.I):
        await shell("am", "start", "-a", "android.intent.action.VIEW", "-d", "'" + t.replace("'", "'\\''") + "'")
        return f"Opened {t} on the phone."
    if t.lower() == "camera":
        await shell("am", "start", "-a", KNOWN_APPS["camera"])
        return "Opened the camera on the phone."
    pkg = match_package(t, await packages())
    if not pkg:
        raise PhoneError(f"No app on the phone matches '{t}'.")
    await shell("monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1")
    return f"Opened {pkg} on the phone."


async def describe() -> str:
    """Which phone, which app is in front, the battery."""
    s = await serial()
    rows = [d for d in await devices() if d["serial"] == s]
    model = rows[0]["model"] if rows and rows[0]["model"] else s
    front = await front_app()
    battery = await shell("dumpsys", "battery")
    level = re.search(r"level:\s*(\d+)", battery)
    awake = await shell("dumpsys", "power")
    on = "screen on" if re.search(r"mWakefulness=Awake", awake) else "screen off"
    return f"Phone {model} ({s}) connected; {on}; in front: {front or 'unknown'}; battery {level.group(1) + '%' if level else 'unknown'}."
