#!/usr/bin/env python3
"""Launch SYRAX with one command on Windows, Linux and macOS.

    python syrax.py                     production UI (built when sources changed)
    python syrax.py --dev               hot-reloading dev UI
    python syrax.py --setup             only install: venv, Python deps, npm, config
    python syrax.py --install-service   start SYRAX at login (systemd / Task Scheduler / launchd)
    python syrax.py --uninstall-service remove the login service
    python syrax.py --status            show the login service
    python syrax.py --gate              run the release gate (pytest, tsc, eslint, build...)
    python syrax.py --backup            verified copy of the journal and config into backend/config/backups
    python syrax.py --restore DIR       put a backup folder back (SYRAX must be stopped)

Missing pieces are installed on first run: the backend venv (uv or venv),
Python requirements, frontend node_modules, and config.toml from the example.
`./syrax.sh` and `.\\syrax.ps1` are thin wrappers around this file.

Environment: SYRAX_PORT (backend, 8765), SYRAX_UI_PORT (UI, 3000),
SYRAX_OPEN_UI=1 (open the browser once both answer). Both servers listen on
127.0.0.1 only.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / ".venv"
CONFIG = BACKEND / "config" / "config.toml"
CONFIG_EXAMPLE = BACKEND / "config" / "config.syrax.example.toml"
LOG = ROOT / "syrax.log"
PID_FILE = ROOT / "syrax.pid"  # the launcher of the running SYRAX; --stop kills its process tree

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
LINUX = not WINDOWS and not MACOS

BACKEND_PORT = int(os.getenv("SYRAX_PORT", "8765"))
UI_PORT = int(os.getenv("SYRAX_UI_PORT", "3000"))
SERVICE_NAME = "syrax"
LAUNCHD_LABEL = "com.syrax.agent"


_OUTPUT_IS_LOG = sys.stdout is None or sys.stderr is None
if _OUTPUT_IS_LOG:  # pythonw (the Windows login task) has no console
    _log = open(LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log


def _note(msg: str) -> None:
    """A service launcher's decisions belong in syrax.log even when its output
    goes nowhere: a self-restart starts it detached with stdout sent to NUL.
    Live 2026-10-10: it stepped aside without a word and SYRAX stayed down."""
    if "--service" in sys.argv and not _OUTPUT_IS_LOG:
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} SYRAX launcher: {msg}\n")
        except OSError:
            pass


def say(msg: str) -> None:
    sys.stdout.write(f"SYRAX: {msg}\n")
    sys.stdout.flush()
    _note(msg)


def die(msg: str, code: int = 1) -> "None":
    sys.stderr.write(f"SYRAX: {msg}\n")
    sys.stderr.flush()
    _note(msg)
    sys.exit(code)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


def venv_pythonw() -> Path:
    """Console-less interpreter for the Windows login task."""
    pw = VENV / "Scripts" / "pythonw.exe"
    return pw if pw.exists() else venv_python()


def which(name: str) -> Optional[str]:
    return shutil.which(name)


def run(cmd: List[str], cwd: Path = ROOT, check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), check=check, **kw)


# ——— setup ———

def setup(verbose: bool = True) -> None:
    """Install whatever is missing. Safe to run every time."""
    py = venv_python()
    if not py.exists():
        say("creating the backend venv (.venv, Python 3.12)...")
        uv = which("uv")
        if uv:
            run([uv, "venv", "--python", "3.12", str(VENV)], cwd=BACKEND)
        else:
            if sys.version_info < (3, 12):
                die("Python 3.12 is needed and `uv` is not installed. Install uv (https://docs.astral.sh/uv/) or Python 3.12.")
            run([sys.executable, "-m", "venv", str(VENV)], cwd=BACKEND)
        if not py.exists():
            die("venv creation failed")
    marker = VENV / ".syrax-requirements"
    req = BACKEND / "requirements-syrax.txt"
    stamp = f"{req.stat().st_mtime_ns}:{(BACKEND / 'requirements.txt').stat().st_mtime_ns}"
    if not marker.exists() or marker.read_text().strip() != stamp:
        say("installing Python requirements (first run takes a few minutes)...")
        uv = which("uv")
        if uv:
            run([uv, "pip", "install", "--python", str(py), "-r", str(req)], cwd=BACKEND)
        else:
            run([str(py), "-m", "pip", "install", "-q", "-r", str(req)], cwd=BACKEND)
        marker.write_text(stamp)
    if not (FRONTEND / "node_modules").is_dir():
        npm = which("npm")
        if not npm:
            die("Node.js is not installed (npm not found). Install Node 22+ from https://nodejs.org and rerun.")
        say("installing frontend packages (npm install)...")
        run([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND)
    if not CONFIG.exists():
        shutil.copy(CONFIG_EXAMPLE, CONFIG)
        say(f"created {CONFIG.relative_to(ROOT)} from the example (no key needed to boot)")
    if verbose:
        say("setup complete")


def check_config() -> None:
    """Fail fast on a broken config instead of leaving the UI running alone."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover — very old launcher interpreter
        return
    try:
        cfg = tomllib.load(open(CONFIG, "rb"))
    except FileNotFoundError:
        die("backend/config/config.toml is missing (run: python syrax.py --setup)")
    except tomllib.TOMLDecodeError as e:
        die(f"config.toml is not valid TOML ({e}). Only TOML goes in that file.")
    if "llm" not in cfg or "daytona" not in cfg:
        die("config.toml needs [llm] and [daytona]. Copy config.syrax.example.toml over it.")


# ——— ports, build ———

def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ui_is_stale() -> bool:
    build_id = FRONTEND / ".next" / "BUILD_ID"
    if not build_id.exists():
        return True
    built = build_id.stat().st_mtime
    for src in ("app", "components", "lib"):
        for p in (FRONTEND / src).rglob("*"):
            if p.is_file() and p.stat().st_mtime > built:
                return True
    return any((FRONTEND / f).stat().st_mtime > built for f in ("package.json", "next.config.ts"))


def build_ui() -> None:
    say("building the UI (first run or sources changed)...")
    proc = run([which("npx") or "npx", "next", "build"], cwd=FRONTEND, check=False, stdout=subprocess.DEVNULL)
    if proc.returncode != 0:
        die("UI build failed. Run: cd frontend && npx next build")


# ——— processes ———

class Component:
    def __init__(self, name: str, cmd: List[str], cwd: Path, log, env: Optional[dict] = None):
        self.name = name
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | (subprocess.CREATE_NO_WINDOW if log is not None else 0) if WINDOWS else 0
        # in the background (log file) the core and UI must not pop console windows onto the desktop
        kw = {"creationflags": flags} if WINDOWS else {"start_new_session": True}
        self.proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=log, stderr=log, env=env, **kw)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self) -> None:
        if not self.alive():
            return
        if WINDOWS:  # the whole tree: npx -> node -> next-server, python -> whisper threads
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


UI_MAX_RESTARTS = 5
UI_RESTART_WINDOW_S = 600


def supervise(core_alive: bool, ui_alive: bool, ui_restarts: List[float], now: float, ui_given_up: bool = False) -> str:
    """What the launcher does about a component that is down.

    The core is the brain: when it dies, SYRAX stops and the service starts it
    again. The UI only observes: it is restarted, at most UI_MAX_RESTARTS times
    in UI_RESTART_WINDOW_S, and the core keeps running either way. Live
    2026-10-10 16:02: the UI process ended without an error and the launcher
    took the core down with it."""
    if not core_alive:
        return "shutdown"
    if ui_alive or ui_given_up:
        return "ok"
    recent = [t for t in ui_restarts if now - t < UI_RESTART_WINDOW_S]
    return "restart_ui" if len(recent) < UI_MAX_RESTARTS else "give_up_ui"


def syrax_answers() -> bool:
    """True only when the process on the backend port is SYRAX: its /health says so.
    A busy port alone proves nothing (live 2026-10-10: another app took 3000)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{BACKEND_PORT}/health", timeout=2) as r:
            return r.status == 200 and json.loads(r.read().decode("utf-8", "replace")).get("name") == "SYRAX"
    except Exception:
        return False


def both_answer() -> bool:
    for url in (f"http://127.0.0.1:{UI_PORT}", f"http://127.0.0.1:{BACKEND_PORT}/health"):
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status != 200:
                    return False
        except Exception:
            return False
    return True


def _uptime_s() -> float:
    try:
        if WINDOWS:
            import ctypes
            return ctypes.windll.kernel32.GetTickCount64() / 1000.0
        if LINUX:
            return float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        pass
    return 1e9


def _ws_token() -> str:
    """The token a connection without an Origin presents (backend/syrax/auth.py), read from its file; "" if none."""
    path = Path(os.getenv("SYRAX_TOKEN_FILE", str(BACKEND / "config" / "ws.token")))
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _stop_url() -> str:
    from urllib.parse import quote

    # probe=1: the launcher is not a human, the daily briefing is not for it; the token: since phase 7 (auth.py) a
    # connection without an Origin needs it, and this one went without, was refused, and the stop never arrived
    tok = _ws_token()
    return f"ws://127.0.0.1:{BACKEND_PORT}/ws?probe=1" + (f"&token={quote(tok)}" if tok else "")


def _cancel_running_task() -> None:
    """Ask the core to cancel its task first, so a restart leaves a cleanly
    cancelled task instead of an INTERRUPTED one with an UNCERTAIN operation
    (each of those waits for a human). The stop says "shutdown": the core holds
    its queue (a queued request must not start just before the kill, review
    2026-10-27) and answers `stopped` once the task has ended."""
    try:
        import asyncio
        import json as _json

        import websockets  # in the backend venv, which runs this launcher

        async def go():
            async with websockets.connect(_stop_url(), max_size=None, open_timeout=5) as ws:
                await ws.send(_json.dumps({"type": "stop", "reason": "shutdown"}))
                deadline = time.time() + 10
                while time.time() < deadline:
                    m = _json.loads(await asyncio.wait_for(ws.recv(), max(0.5, deadline - time.time())))
                    if m.get("type") == "stopped":
                        return

        asyncio.run(go())
    except Exception:
        pass  # not running, no websockets here, or slow: the kill below still happens


def stop() -> int:
    """Stop the running SYRAX (launcher, core, UI) through its pid file."""
    if not PID_FILE.exists():
        say("not running (no pid file).")
        return 0
    _cancel_running_task()
    pid = PID_FILE.read_text().strip()
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except (ProcessLookupError, ValueError):
            pass
    for _ in range(30):
        if not port_in_use(BACKEND_PORT) and not port_in_use(UI_PORT):
            break
        time.sleep(0.5)
    PID_FILE.unlink(missing_ok=True)
    say("stopped.")
    return 0


def start_detached() -> int:
    """Start SYRAX in the background (service mode), independent of this shell."""
    if WINDOWS and subprocess.run(["schtasks", "/Query", "/TN", SERVICE_NAME.upper()], capture_output=True).returncode == 0:
        subprocess.run(["schtasks", "/Run", "/TN", SERVICE_NAME.upper()], capture_output=True)
    else:
        kw = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
        subprocess.Popen(launcher_cmd(hidden=True), cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    for _ in range(120):
        if both_answer():
            say("running.")
            return 0
        time.sleep(1)
    say(f"did not answer within 120 s; see {LOG}")
    return 1


# What the running service turns on (each can be turned off by setting it to 0):
# M1, isolated evolution (SYRAX's own work happens in worktrees), M3, the rise
# ledger publishing itself once a day through the same release path, M2, the
# weekly code benchmark that decides which brain starts release work, and the
# feature catalog (prebuilt skills installed; low-risk features taken up when idle).
SERVICE_DEFAULTS = {"SYRAX_ISOLATE": "1", "SYRAX_PUBLISH_RISE": "1", "SYRAX_CODEBENCH": "1", "SYRAX_FEATURES": "1"}


@contextmanager
def service_defaults():
    """Set SERVICE_DEFAULTS that are not already set, only while the core is
    spawned (it inherits them), then restore this process's environment.
    Live 2026-10-11: setting them for good leaked into the test suite, which
    imports this launcher, and test cycles ran real ledger publishes."""
    added = [k for k in SERVICE_DEFAULTS if k not in os.environ]
    for k in added:
        os.environ[k] = SERVICE_DEFAULTS[k]
    try:
        yield
    finally:
        for k in added:
            os.environ.pop(k, None)


HUD = ROOT / "hud"


def hud_exe() -> Optional[Path]:
    """The desktop HUD's Electron, once `npm install` has run in hud/; None means open the browser UI."""
    exe = HUD / "node_modules" / "electron" / "dist" / ("electron.exe" if os.name == "nt" else "electron")
    return exe if exe.is_file() and os.getenv("SYRAX_HUD", "1") != "0" else None


def open_hud(exe: Path) -> None:
    """Start the HUD detached: it is its own window, outlives this launcher, and a second start
    just focuses the first (single-instance lock in hud/main.js)."""
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}  # VS Code leaks it; it makes Electron plain Node
    flags = {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([str(exe), str(HUD)], cwd=str(HUD), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)


# ——— known-good fallback ———
# A self-restart starts whatever main holds. New code lands there only after a GREEN gate, but a core that still
# does not come up (an import error, a hang before /health) left nothing to bring SYRAX back (audit 2026-10-27,
# item 6). The launcher records the commit of a core that answered /health and kept running for
# KNOWN_GOOD_SETTLE_S; when a core from main does not come up, it runs that commit from a git worktree of its own
# (FALLBACK_TREE). Main and the repository's working tree are never reset, checked out or reverted.

KNOWN_GOOD = BACKEND / "config" / "known_good.json"  # {"commit", "at"} and, after a fallback, {"bad", "bad_at", "bad_why"}
FALLBACK_TREE = ROOT / ".syrax" / "known-good"
KNOWN_GOOD_SETTLE_S = 120  # answered /health and still running this long after: the commit is known-good
CORE_BOOT_DEADLINE_S = 180  # no /health answer this long after the start: the core did not come up
# Files the core reads only from its own backend/config, with no variable to point it elsewhere: hard links in the
# fallback tree, so it reads the same file (config.toml holds keys), never a copy.
FALLBACK_LINKED = ("config.toml", "mcp.json")
# The fallback runs older code from a detached worktree: it serves the human and does no work on its own code. A
# release there would commit to that detached tree, and a self-restart would start the failed commit again.
FALLBACK_OFF = {"SYRAX_AUTONOMY": "0", "SYRAX_SELF_RESTART": "0", "SYRAX_ISOLATE": "0", "SYRAX_PUBLISH_RISE": "0",
                "SYRAX_CODEBENCH": "0", "SYRAX_FEATURES": "0", "SYRAX_AUTOPUSH": "0"}


def core_cmd() -> List[str]:
    return [str(venv_python()), "-m", "syrax.server"]


def head_commit(root: Optional[Path] = None) -> Optional[str]:
    """The full sha main's working tree is at (the code a core started now runs), or None without git."""
    try:
        p = subprocess.run(["git", "-C", str(root or ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (p.stdout or "").strip()
    return out if p.returncode == 0 and out else None


def read_known_good(path: Optional[Path] = None) -> dict:
    try:
        data = json.loads((path or KNOWN_GOOD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_known_good(data: dict, path: Optional[Path] = None) -> None:
    """Atomically: a crash mid-write leaves the old file whole, never half of a new one."""
    path = path or KNOWN_GOOD
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


BAD_KEYS = ("bad", "bad_at", "bad_why")


def mark_known_good(commit: str, now: Optional[float] = None, path: Optional[Path] = None) -> dict:
    data = read_known_good(path)
    data.update(commit=commit, at=round(now if now is not None else time.time(), 3))
    if data.get("bad") == commit:  # it came up after all: a human restart, or a slow start the first time
        for k in BAD_KEYS:
            data.pop(k, None)
    write_known_good(data, path)
    return data


def mark_bad(commit: str, why: str, now: Optional[float] = None, path: Optional[Path] = None) -> dict:
    data = read_known_good(path)
    data.update(bad=commit, bad_at=round(now if now is not None else time.time(), 3), bad_why=str(why)[:300])
    write_known_good(data, path)
    return data


def clear_bad(path: Optional[Path] = None) -> bool:
    """A human restart: main is tried again even if it failed before. True when there was a mark."""
    data = read_known_good(path)
    if "bad" not in data:
        return False
    for k in BAD_KEYS:
        data.pop(k, None)
    write_known_good(data, path)
    return True


def fallback_target(commit: Optional[str], known: dict) -> Optional[str]:
    """The known-good commit to fall back to from `commit`; None when none is recorded or it is `commit` itself."""
    good = known.get("commit")
    return good if isinstance(good, str) and good and commit and good != commit else None


def known_bad(commit: Optional[str], known: dict) -> bool:
    """`commit` already failed to come up and main has not moved since: start the known-good commit straight away
    instead of failing again. A newer commit on main is tried; a human `--restart` clears the mark."""
    return bool(commit) and known.get("bad") == commit and fallback_target(commit, known) is not None


def decide_fallback(core_alive: bool, answered_at: Optional[float], started: float, now: float,
                    commit: Optional[str], known: dict) -> Optional[str]:
    """Why the core started from main at `started` counts as not having come up, or None. Asked until the core is
    known-good: it exited before then, or it never answered /health within CORE_BOOT_DEADLINE_S. None as well when
    there is nothing to fall back to (then the launcher does what it always did)."""
    if fallback_target(commit, known) is None:
        return None
    ran = int(now - started)
    if not core_alive:
        if answered_at is None:
            return f"the core exited {ran} s after it started, before it answered /health"
        return f"the core exited {ran} s after it started, before it had run {KNOWN_GOOD_SETTLE_S} s"
    if answered_at is None and now - started >= CORE_BOOT_DEADLINE_S:
        return f"the core did not answer /health within {CORE_BOOT_DEADLINE_S} s"
    return None


def known_good_due(answered_at: Optional[float], now: float) -> bool:
    """The core first answered /health KNOWN_GOOD_SETTLE_S ago (and has not exited: the caller checks)."""
    return answered_at is not None and now - answered_at >= KNOWN_GOOD_SETTLE_S


def fallback_env(base: dict, live_backend: Path, commit: str) -> dict:
    """The fallback core's environment. Its code lives in the worktree, so every runtime file it can be pointed at
    is pointed at the live one (the same journal, keys, memory and skills, never a copy); an explicit setting stays.
    Its own work on its code is off (FALLBACK_OFF)."""
    env = dict(base)
    cfg = live_backend / "config"
    for k, v in (("SYRAX_JOURNAL_FILE", cfg / "journal.db"), ("SYRAX_TOKEN_FILE", cfg / "ws.token"),
                 ("SYRAX_BRAINS_FILE", cfg / "brains.json"), ("SYRAX_MEMORY_FILE", cfg / "memory.json"),
                 ("SYRAX_HISTORY_FILE", cfg / "history.jsonl"), ("SYRAX_EXPORT_DIR", cfg / "exports"),
                 ("SYRAX_SKILLS_DIR", live_backend / "skills"), ("SYRAX_BROWSER_PROFILE", live_backend / ".syrax-browser")):
        env.setdefault(k, str(v))
    env.update(FALLBACK_OFF)
    env["SYRAX_FALLBACK"] = commit
    return env


def fallback_tree_cmds(root: Path, tree: Path, commit: str, current: Optional[str]) -> List[List[str]]:
    """The git commands that put the fallback worktree at `commit`. `current` is the commit it is at, None when it is
    not a worktree yet. Only `worktree add` runs in the repository (it writes .git/worktrees, not the working tree);
    `checkout` runs inside the fallback worktree."""
    if current == commit:
        return []
    if current is None:  # --force: a registration left behind by a deleted folder does not block it
        return [["git", "-C", str(root), "worktree", "add", "--force", "--detach", str(tree), commit]]
    return [["git", "-C", str(tree), "checkout", "--detach", commit]]


def ensure_fallback_tree(commit: str, root: Optional[Path] = None, tree: Optional[Path] = None, runner=None) -> Optional[str]:
    """Put the fallback worktree at `commit`; returns the commit it is at afterwards (None: there is no usable tree).
    A checkout that fails leaves it at its earlier commit, which was known-good too."""
    root, tree, runner = root or ROOT, tree or FALLBACK_TREE, runner or subprocess.run
    if tree.resolve() == root.resolve():
        say("refusing a fallback worktree at the repository itself")
        return None

    def git(cmd: List[str]) -> subprocess.CompletedProcess:
        try:
            return runner(cmd, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as e:
            return subprocess.CompletedProcess(cmd, 1, "", str(e))

    def at() -> Optional[str]:
        # only a folder that is its own worktree: `git -C` in a plain folder would find the repository above it
        if not (tree / ".git").exists():
            return None
        p = git(["git", "-C", str(tree), "rev-parse", "--show-toplevel", "HEAD"])
        lines = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]  # a path may hold spaces
        if p.returncode != 0 or len(lines) != 2:
            return None
        try:
            if Path(lines[0]).resolve() != tree.resolve():
                return None
        except OSError:
            return None
        return lines[1]

    for cmd in fallback_tree_cmds(root, tree, commit, at()):
        p = git(cmd)
        if p.returncode != 0:
            say(f"git {' '.join(cmd[3:5])} for the fallback failed: {((p.stderr or '') + (p.stdout or '')).strip()[-300:]}")
            break
    return at()


def link_live_files(tree_backend: Path, live_backend: Optional[Path] = None, names=FALLBACK_LINKED) -> List[str]:
    """Hard-link FALLBACK_LINKED from the live backend/config into the fallback tree's (the same file, not a copy).
    Only the fallback tree's own entry is ever replaced."""
    live_backend = live_backend or BACKEND
    if tree_backend.resolve() == live_backend.resolve():
        return []
    linked = []
    for name in names:
        src, dst = live_backend / "config" / name, tree_backend / "config" / name
        if not src.is_file():
            continue
        try:
            if dst.exists() or dst.is_symlink():
                if dst.exists() and os.path.samefile(src, dst):
                    linked.append(name)
                    continue
                dst.unlink()
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.link(src, dst)
            linked.append(name)
        except OSError as e:
            say(f"could not link {name} into the fallback tree ({e}); its core reads the example in its place")
    return linked


def journal_fallback(tree_backend: Path, env: dict, bad: str, good: str, why: str) -> bool:
    """`restart.fallback` and the human's notice, written by the known-good code (syrax/knowngood.py) while no core
    owns the journal."""
    cmd = [str(venv_python()), "-m", "syrax.knowngood", "--from", bad, "--to", good, "--why", why]
    try:
        p = subprocess.run(cmd, cwd=str(tree_backend), env=env, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        say(f"could not journal the fallback: {e}")
        return False
    if p.returncode != 0:
        say(f"could not journal the fallback (exit {p.returncode}): {((p.stderr or '') + (p.stdout or '')).strip()[-300:]}")
        return False
    return True


def wait_core_gone(core, timeout: float = 15.0) -> None:
    """Until the stopped core has exited and released the port and the journal (the next core needs both)."""
    end = time.time() + timeout
    while time.time() < end and (core.alive() or port_in_use(BACKEND_PORT)):
        time.sleep(0.5)


def run_fallback(bad: str, good: str, why: str, log) -> "Component":
    """Start the core from the fallback tree, which ensure_fallback_tree put at `good`; the failed core has stopped."""
    backend = FALLBACK_TREE / "backend"
    link_live_files(backend)
    env = fallback_env(dict(os.environ), BACKEND, good)
    try:
        if read_known_good().get("bad") != bad:  # a start that skips a known-bad commit keeps its first reason
            mark_bad(bad, why)
    except OSError as e:
        say(f"could not record {bad[:10]} as known-bad: {e}")
    journal_fallback(backend, env, bad, good, why)
    core = Component("core", core_cmd(), backend, log, env=env)
    say(f"core  : the known-good commit {good[:10]} runs from {backend}; main ({bad[:10]}) and the working tree are "
        "untouched; self-improvement is off. Fix main, then: python syrax.py --restart")
    return core


def launch(dev: bool, service: bool, watch: bool = False) -> int:
    """Run the core and the UI until the core exits. `watch` (main() sets it; launch() called directly, as the tests
    do, keeps the old behaviour): record the commit of a core that came up as known-good, and in service mode, when
    the core from main does not come up, run the known-good commit instead (see the section above)."""
    setup(verbose=False)
    check_config()
    busy = [port for port in (BACKEND_PORT, UI_PORT) if port_in_use(port)]
    if busy:
        if syrax_answers():
            if service:  # as a login service, another running SYRAX is fine: step aside
                say(f"SYRAX already answers on port {BACKEND_PORT}; stepping aside.")
                return 0
            die("SYRAX is already running.")
        die(f"port {', '.join(map(str, busy))} is in use by another program, and SYRAX is not running. "
            "Free the port, or move SYRAX with SYRAX_UI_PORT / SYRAX_PORT (and SYRAX_ALLOWED_ORIGINS).")
    if not dev and ui_is_stale():
        build_ui()

    log = None
    if service and not LINUX:  # systemd keeps the journal itself; elsewhere the service logs to a file
        log = open(LOG, "ab", buffering=0)
    npx = which("npx") or "npx"
    env_ui = ["--hostname", "127.0.0.1", "--port", str(UI_PORT)]
    comps: List[Component] = []
    stopping = False

    def shutdown(*_):
        nonlocal stopping
        if stopping:
            return
        stopping = True
        for c in comps:
            c.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    commit = head_commit() if watch else None
    known = read_known_good() if commit else {}
    may_fall_back = service and commit is not None  # at most once per launch
    in_fallback = False
    try:
        ui_cmd = [npx, "next", "dev" if dev else "start", *env_ui]
        core = None
        if may_fall_back and known_bad(commit, known):
            may_fall_back = False
            why = f"it did not come up at its last start ({known.get('bad_why') or 'see syrax.log'}) and main has not moved"
            say(f"commit {commit[:10]}: {why}; starting the known-good commit {known['commit'][:10]} instead.")
            at = ensure_fallback_tree(known["commit"])
            if at:
                core, in_fallback = run_fallback(commit, at, why, log), True
            else:
                say("the fallback worktree could not be prepared; starting main after all.")
        if core is None:
            with service_defaults():
                core = Component("core", core_cmd(), BACKEND, log)
        comps.append(core)
        comps.append(Component("ui", ui_cmd, FRONTEND, log))
        say(f"core  : ws://127.0.0.1:{BACKEND_PORT}/ws")
        say(f"orb UI: http://localhost:{UI_PORT}")
        if hud_exe():
            say(f"HUD   : http://127.0.0.1:{BACKEND_PORT}/hud (desktop app, hud/SYRAX.cmd)")
        PID_FILE.write_text(str(os.getpid()))
        # a login start opens the UI; a restart minutes or hours later does not
        open_ui = os.getenv("SYRAX_OPEN_UI") == "1" or (service and os.getenv("SYRAX_OPEN_UI") != "0" and _uptime_s() < 600)
        started = time.time()
        core_started, answered_at = started, None
        settled = commit is None  # nothing left to watch: recorded as known-good, or the fallback answered
        deadline_said = False
        ui_restarts: List[float] = []
        ui_given_up = False
        while not stopping:
            time.sleep(1)
            if not settled:
                now = time.time()
                alive = comps[0].alive()
                if answered_at is None and alive and syrax_answers():
                    answered_at = now
                    if in_fallback:
                        say(f"the known-good core answers on port {BACKEND_PORT}.")
                        settled = True
                why = decide_fallback(alive, answered_at, core_started, now, commit, known) if may_fall_back and not in_fallback else None
                if why and not alive:
                    time.sleep(2)  # `--stop` kills this launcher together with the core: never act on a death it caused
                if why and not stopping:
                    may_fall_back = False
                    good = fallback_target(commit, known)
                    say(f"commit {commit[:10]}: {why}; falling back to the known-good commit {good[:10]} "
                        f"(worktree {FALLBACK_TREE}); main and the working tree are not touched.")
                    at = ensure_fallback_tree(good)
                    if at:
                        comps[0].stop()
                        wait_core_gone(comps[0])
                        comps[0], in_fallback = run_fallback(commit, at, why, log), True
                        core_started, answered_at = time.time(), None
                        continue
                    say("the fallback worktree could not be prepared; nothing else to fall back to.")
                elif not in_fallback and alive and known_good_due(answered_at, now) and syrax_answers():
                    try:
                        mark_known_good(commit)
                        say(f"commit {commit[:10]} answered for {KNOWN_GOOD_SETTLE_S} s: recorded as known-good.")
                    except OSError as e:
                        say(f"could not record the known-good commit: {e}")
                    settled = True
                if answered_at is None and not deadline_said and now - core_started >= CORE_BOOT_DEADLINE_S and comps[0].alive():
                    deadline_said = True
                    say(f"the core has not answered /health in {CORE_BOOT_DEADLINE_S} s; still waiting for it.")
            action = supervise(comps[0].alive(), comps[1].alive(), ui_restarts, time.time(), ui_given_up)
            if action == "shutdown":
                if not stopping:
                    say(f"core exited (code {comps[0].proc.returncode}), shutting down.")
                break
            if action == "restart_ui":
                say(f"ui exited (code {comps[1].proc.returncode}); restarting it, the core keeps running.")
                ui_restarts.append(time.time())
                comps[1] = Component("ui", ui_cmd, FRONTEND, log)
            elif action == "give_up_ui":
                say(f"ui exited {UI_MAX_RESTARTS} times in {UI_RESTART_WINDOW_S // 60} min; the core keeps running without it.")
                ui_given_up = True
            if open_ui and time.time() - started < 120 and both_answer():
                exe = hud_exe()  # the desktop HUD is the main face when it is installed; the browser UI otherwise
                if exe:
                    open_hud(exe)
                else:
                    webbrowser.open(f"http://localhost:{UI_PORT}")
                open_ui = False
    finally:
        shutdown()
        if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
            PID_FILE.unlink(missing_ok=True)
        if log:
            log.close()
    return 0


# ——— login services ———

def launcher_cmd(hidden: bool = False) -> List[str]:
    py = venv_pythonw() if (WINDOWS and hidden) else venv_python()
    return [str(py), str(ROOT / "syrax.py"), "--service"]


def _startup_script() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))) / "Microsoft/Windows/Start Menu/Programs/Startup/SYRAX.vbs"


def install_service() -> None:
    setup(verbose=False)
    if LINUX:
        unit_dir = Path.home() / ".config/systemd/user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit = unit_dir / f"{SERVICE_NAME}.service"
        exec_start = " ".join(f'"{a}"' for a in launcher_cmd())
        unit.write_text(f"""[Unit]
Description=SYRAX, son of Ultron
After=graphical-session.target network-online.target
PartOf=graphical-session.target

[Service]
Type=simple
WorkingDirectory={ROOT}
ExecStart={exec_start}
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=20

[Install]
WantedBy=graphical-session.target
""")
        run(["systemctl", "--user", "daemon-reload"])
        run(["systemctl", "--user", "enable", f"{SERVICE_NAME}.service"])
        say("will start automatically at your next login.")
        say(f"start now: systemctl --user start {SERVICE_NAME}    logs: journalctl --user -u {SERVICE_NAME} -f")
    elif MACOS:
        agents = Path.home() / "Library/LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        plist = agents / f"{LAUNCHD_LABEL}.plist"
        args = "".join(f"        <string>{a}</string>\n" for a in launcher_cmd())
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args}    </array>
    <key>WorkingDirectory</key><string>{ROOT}</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
    <key>StandardOutPath</key><string>{LOG}</string>
    <key>StandardErrorPath</key><string>{LOG}</string>
    <key>EnvironmentVariables</key><dict><key>PATH</key><string>{os.environ.get('PATH', '')}</string></dict>
</dict>
</plist>
""")
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        run(["launchctl", "load", "-w", str(plist)])
        say("will start automatically at your next login (launchd).")
        say(f"start now: launchctl start {LAUNCHD_LABEL}    logs: tail -f {LOG}")
    else:
        tr = " ".join(f'"{a}"' for a in launcher_cmd(hidden=True))
        made = subprocess.run(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", SERVICE_NAME.upper(), "/TR", tr, "/RL", "LIMITED"],
                              capture_output=True, text=True)
        if made.returncode == 0:
            say("will start automatically at your next login (Task Scheduler).")
        else:  # an ONLOGON trigger needs admin; the user's Startup folder does not
            vbs = _startup_script()
            args = " ".join(f'""{a}""' for a in launcher_cmd(hidden=True))
            vbs.write_text(f'CreateObject("WScript.Shell").Run "{args}", 0, False\r\n', encoding="utf-8")
            say(f"will start automatically at your next login (Startup folder: {vbs.name}; Task Scheduler needs admin).")
        say(f"start now: python syrax.py --restart    logs: {LOG}")


def uninstall_service() -> None:
    if LINUX:
        subprocess.run(["systemctl", "--user", "disable", "--now", f"{SERVICE_NAME}.service"], capture_output=True)
        unit = Path.home() / ".config/systemd/user" / f"{SERVICE_NAME}.service"
        unit.unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    elif MACOS:
        plist = Path.home() / "Library/LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        subprocess.run(["launchctl", "unload", "-w", str(plist)], capture_output=True)
        plist.unlink(missing_ok=True)
    else:
        subprocess.run(["schtasks", "/End", "/TN", SERVICE_NAME.upper()], capture_output=True)
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", SERVICE_NAME.upper()], capture_output=True)
        _startup_script().unlink(missing_ok=True)
    say("login service removed.")


def service_status() -> int:
    if LINUX:
        return subprocess.run(["systemctl", "--user", "status", f"{SERVICE_NAME}.service", "--no-pager"]).returncode
    if MACOS:
        return subprocess.run(["launchctl", "list", LAUNCHD_LABEL]).returncode
    if _startup_script().exists():
        say(f"login start: Startup folder ({_startup_script()})")
    say("running" if PID_FILE.exists() and both_answer() else "not running")
    return subprocess.run(["schtasks", "/Query", "/TN", SERVICE_NAME.upper(), "/V", "/FO", "LIST"], capture_output=True).returncode


# ——— main ———

# 2026-10-29: started from a Claude Code shell, SYRAX inherited that session's token (CLAUDE_CODE_MESSAGING_TOKEN) and
# passed it to everything it ran. Nothing SYRAX starts needs the editor session's variables.
FOREIGN_SESSION_PREFIXES = ("CLAUDE_CODE_",)
FOREIGN_SESSION_NAMES = ("CLAUDECODE",)


def drop_foreign_session_env(environ=None) -> List[str]:
    env = os.environ if environ is None else environ
    gone = sorted(k for k in list(env) if k.startswith(FOREIGN_SESSION_PREFIXES) or k in FOREIGN_SESSION_NAMES)
    for k in gone:
        env.pop(k, None)
    return gone


def main(argv: Optional[List[str]] = None) -> int:
    drop_foreign_session_env()
    ap = argparse.ArgumentParser(description="Run SYRAX (core + orb UI) on any OS.", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dev", action="store_true", help="hot-reloading dev UI")
    ap.add_argument("--setup", action="store_true", help="install what is missing and exit")
    ap.add_argument("--install-service", action="store_true", help="start SYRAX at login")
    ap.add_argument("--uninstall-service", action="store_true")
    ap.add_argument("--status", action="store_true", help="login service status")
    ap.add_argument("--gate", action="store_true", help="run the release gate and exit")
    ap.add_argument("--backup", action="store_true", help="copy the journal, brains, memory and config into backend/config/backups (verified, 7 kept)")
    ap.add_argument("--restore", metavar="DIR", help="put a backup folder back into backend/config; refuses while SYRAX runs")
    ap.add_argument("--token", action="store_true", help="print the token a non-browser client needs for /ws, /live and the voice endpoints")
    ap.add_argument("--phone", choices=("on", "off", "show"), help="the phone page (watch + emergency stop only, on the home WiFi): turn it on or off, or print its link; on/off take effect at the next restart")
    ap.add_argument("--stop", action="store_true", help="stop the running SYRAX")
    ap.add_argument("--restart", action="store_true", help="stop, then start in the background")
    ap.add_argument("--respawn", action="store_true", help=argparse.SUPPRESS)  # SYRAX restarting itself
    ap.add_argument("--self-restart", action="store_true", help=argparse.SUPPRESS)  # set by --respawn: not a human's restart
    ap.add_argument("--service", action="store_true", help=argparse.SUPPRESS)  # set by the login service
    a = ap.parse_args(argv)
    if a.token:
        sys.path.insert(0, str(BACKEND))
        from syrax import auth

        print(auth.token())
        return 0
    if a.phone:
        sys.path.insert(0, str(BACKEND))
        from syrax import phone

        if a.phone in ("on", "off"):
            phone.save(a.phone == "on")
            print(f"phone page {a.phone}: run python syrax.py --restart to apply.")
        st = phone.settings()
        if st["enabled"]:
            print(f"Open on your phone (same WiFi), keep this link private:\n{phone.link()}")
            print("The page can watch SYRAX and press the emergency stop, nothing more.")
        else:
            print("phone page is off (python syrax.py --phone on)")
        return 0
    if a.setup:
        setup()
        return 0
    if a.install_service:
        install_service()
        return 0
    if a.uninstall_service:
        uninstall_service()
        return 0
    if a.status:
        return service_status()
    if a.stop:
        return stop()
    if a.restart:
        if not a.self_restart:  # a human restart tries main again, even a commit that failed to come up before
            try:
                if clear_bad():
                    say("main is tried again: the known-bad mark is cleared (a human restart).")
            except OSError as e:
                say(f"could not clear the known-bad mark: {e}")
        stop()
        return start_detached()
    if a.respawn:  # detach once more so the restarter outlives SYRAX's process tree
        kw = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
        subprocess.Popen([sys.executable, str(ROOT / "syrax.py"), "--restart", "--self-restart"], cwd=str(ROOT),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        return 0
    if a.gate:
        setup(verbose=False)
        return subprocess.run([str(venv_python()), "-m", "syrax.verify"], cwd=str(BACKEND)).returncode
    if a.backup or a.restore:  # syrax.backup is stdlib only: the venv is all it needs, even on a bare machine
        if not venv_python().exists():
            setup(verbose=False)
        cmd = ["--snapshot"] if a.backup else ["--restore", str(Path(a.restore).resolve())]
        return subprocess.run([str(venv_python()), "-m", "syrax.backup", *cmd], cwd=str(BACKEND)).returncode
    return launch(dev=a.dev, service=a.service, watch=True)


if __name__ == "__main__":
    sys.exit(main())
