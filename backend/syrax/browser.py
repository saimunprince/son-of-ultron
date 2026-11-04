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
import re
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



# Browser Use's daemon could not reach the browser, so the call's code never ran (live
# 2026-10-13 10:07: the first call after a reboot, while Chrome restarted itself once).
# A connection lost in the middle of a call is not here: its code may have run.
NEVER_RAN = re.compile(r"unreachable after \d+s|daemon \S+ didn't come up")


def never_ran(result: str) -> bool:
    return bool(NEVER_RAN.search(str(result or "")))


def user_configured(env: Optional[dict] = None) -> bool:
    """True when the human pointed Browser Use somewhere else. SYRAX's own CDP
    URL does not count: SYRAX sets it below, and every process SYRAX starts
    inherits it. Live 2026-10-12: after a self-restart the new core took its
    own inherited URL for the human's setting, never launched its browser,
    and every browser call failed ("BU_CDP_URL ... unreachable after 30s",
    found by the browser_read quality case)."""
    env = os.environ if env is None else env
    if any(env.get(k) for k in ("BU_CDP_WS", "BROWSER_USE_API_KEY", "BU_BROWSER_ID")):
        return True
    url = str(env.get("BU_CDP_URL") or "")
    return bool(url) and url.rstrip("/") != CDP_URL


_USER_CONFIGURED = user_configured()
MANAGED = not _USER_CONFIGURED and os.getenv("SYRAX_BROWSER", "1") != "0"

if MANAGED:
    # Read by Manus when it spawns the Browser Use MCP server.
    os.environ["BU_CDP_URL"] = CDP_URL

_proc: Optional[subprocess.Popen] = None
# Audit 2026-11-01 (I-12): a browser left by a crashed SYRAX answered on the port and was adopted, but shutdown only
# closed `_proc`, so it outlived every later SYRAX. Its pid is kept in the profile; an adopted one is closed too.
PIDFILE_NAME = "syrax-browser.pid"
_adopted: Optional[int] = None


def _ours(pid: int) -> bool:
    """Whether `pid` is still a browser on SYRAX's profile (a pid the system reused for something else is not)."""
    try:
        import psutil

        return any(str(PROFILE) in part for part in psutil.Process(pid).cmdline())
    except Exception:
        return False


def _adopt() -> None:
    global _adopted
    try:
        pid = int((PROFILE / PIDFILE_NAME).read_text().strip())
    except (OSError, ValueError):
        return
    _adopted = pid if _ours(pid) else None
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
    global _proc
    if not MANAGED:
        return None
    async with _lock:
        if await _alive():
            if _proc is None and _adopted is None:
                _adopt()
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
        logger.info(f"Starting SYRAX browser: {chrome} (port {PORT})")
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
        _proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **group)
        try:
            (PROFILE / PIDFILE_NAME).write_text(str(_proc.pid))
        except OSError:
            pass
        for _ in range(60):
            if await _alive():
                return None
            if _proc.poll() is not None:
                return f"SYRAX browser exited right away (code {_proc.returncode})."
            await asyncio.sleep(0.25)
        return f"SYRAX browser did not open its debug port {PORT} in 15s."


def _close_adopted() -> None:
    global _adopted
    pid, _adopted = _adopted, None
    if pid is None or not _ours(pid):
        return
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            os.killpg(pid, signal.SIGTERM)  # Chrome runs in its own session, so its pid is its group
    except (ProcessLookupError, PermissionError, OSError, subprocess.TimeoutExpired):
        pass
    try:
        (PROFILE / PIDFILE_NAME).unlink()
    except OSError:
        pass


def shutdown() -> None:
    """Close the SYRAX browser and all its helper processes, also one adopted from an earlier SYRAX."""
    global _proc
    _close_adopted()
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
