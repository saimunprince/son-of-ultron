"""SYRAX's own browser for the Browser Use MCP tools.

Browser Use CLI 3.0 does not launch a browser: it attaches to a Chrome that
already exposes remote debugging. Out of the box that fails with
"DevToolsActivePort not found". SYRAX runs a dedicated Chrome with its own
profile (your personal browser is never touched) and points Browser Use at it
through BU_CDP_URL. The browser starts lazily on the first browser tool call.
"""

from __future__ import annotations

import asyncio
import atexit
import glob
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

import httpx

from app.config import PROJECT_ROOT
from app.logger import logger

PORT = int(os.getenv("SYRAX_BROWSER_PORT", "9333"))
PROFILE = Path(os.getenv("SYRAX_BROWSER_PROFILE", PROJECT_ROOT / ".syrax-browser"))
HEADLESS = os.getenv("SYRAX_BROWSER_HEADLESS", "0").lower() in {"1", "true", "yes"}
CDP_URL = f"http://127.0.0.1:{PORT}"

_USER_CONFIGURED = any(
    os.getenv(k) for k in ("BU_CDP_URL", "BU_CDP_WS", "BROWSER_USE_API_KEY", "BU_BROWSER_ID")
)
MANAGED = not _USER_CONFIGURED and os.getenv("SYRAX_BROWSER", "1") != "0"

if MANAGED:
    # Read by Manus when it spawns the Browser Use MCP server.
    os.environ["BU_CDP_URL"] = CDP_URL

_proc: Optional[subprocess.Popen] = None
_lock = asyncio.Lock()


WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
MAC_BROWSERS = (
    "Google Chrome.app/Contents/MacOS/Google Chrome",
    "Chromium.app/Contents/MacOS/Chromium",
    "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "Brave Browser.app/Contents/MacOS/Brave Browser",
)
WIN_BROWSERS = (
    r"Google\Chrome\Application\chrome.exe",
    r"Microsoft\Edge\Application\msedge.exe",
    r"BraveSoftware\Brave-Browser\Application\brave.exe",
    r"Chromium\Application\chrome.exe",
)


def find_chrome() -> Optional[str]:
    explicit = os.getenv("SYRAX_BROWSER_BIN")
    if explicit:
        return explicit
    if WINDOWS:
        roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        for root in filter(None, roots):
            for rel in WIN_BROWSERS:
                path = os.path.join(root, rel)
                if os.path.exists(path):
                    return path
        for name in ("chrome", "msedge", "brave", "chromium"):
            path = shutil.which(name)
            if path:
                return path
        return None
    if MACOS:
        for root in ("/Applications", str(Path.home() / "Applications")):
            for rel in MAC_BROWSERS:
                path = os.path.join(root, rel)
                if os.path.exists(path):
                    return path
        return None
    for name in (
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
        "microsoft-edge", "microsoft-edge-stable", "brave-browser",
    ):
        path = shutil.which(name)
        if path:
            return path
    # Playwright's bundled Chromium as a last resort
    found = sorted(glob.glob(str(Path.home() / ".cache/ms-playwright/chromium-*/chrome-linux*/chrome")))
    return found[-1] if found else None


async def _alive() -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as http:
            r = await http.get(f"{CDP_URL}/json/version")
            return r.status_code == 200
    except Exception:
        return False


async def ensure_browser() -> Optional[str]:
    """Make sure the SYRAX browser is up. Returns an error message or None."""
    if not MANAGED:
        return None
    async with _lock:
        if await _alive():
            return None
        chrome = find_chrome()
        if not chrome:
            return (
                "No Chrome/Chromium/Edge/Brave found. Install Google Chrome or set "
                "SYRAX_BROWSER_BIN to a Chromium-based browser."
            )
        PROFILE.mkdir(parents=True, exist_ok=True)
        args = [
            chrome,
            f"--remote-debugging-port={PORT}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            "--window-size=1280,860",
        ]
        if HEADLESS:
            args.append("--headless=new")
        args.append("about:blank")
        global _proc
        logger.info(f"Starting SYRAX browser: {chrome} (port {PORT})")
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
        _proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **group)
        for _ in range(60):
            if await _alive():
                return None
            if _proc.poll() is not None:
                return f"SYRAX browser exited right away (code {_proc.returncode})."
            await asyncio.sleep(0.25)
        return f"SYRAX browser did not open its debug port {PORT} in 15s."


def shutdown() -> None:
    """Close the SYRAX browser and all its helper processes."""
    global _proc
    if _proc and _proc.poll() is None:
        if WINDOWS:  # taskkill /T takes the renderer and GPU helpers down with the browser
            subprocess.run(["taskkill", "/PID", str(_proc.pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            try:
                os.killpg(_proc.pid, signal.SIGTERM)  # own session => own group
                _proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(_proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    _proc = None


atexit.register(shutdown)
