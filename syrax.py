#!/usr/bin/env python3
"""Launch SYRAX with one command on Windows, Linux and macOS.

    python syrax.py                     production UI (built when sources changed)
    python syrax.py --dev               hot-reloading dev UI
    python syrax.py --setup             only install: venv, Python deps, npm, config
    python syrax.py --install-service   start SYRAX at login (systemd / Task Scheduler / launchd)
    python syrax.py --uninstall-service remove the login service
    python syrax.py --status            show the login service
    python syrax.py --gate              run the release gate (pytest, tsc, eslint, build...)

Missing pieces are installed on first run: the backend venv (uv or venv),
Python requirements, frontend node_modules, and config.toml from the example.
`./syrax.sh` and `.\\syrax.ps1` are thin wrappers around this file.

Environment: SYRAX_PORT (backend, 8765), SYRAX_UI_PORT (UI, 3000),
SYRAX_OPEN_UI=1 (open the browser once both answer). Both servers listen on
127.0.0.1 only.
"""

from __future__ import annotations

import argparse
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


if sys.stdout is None or sys.stderr is None:  # pythonw (the Windows login task) has no console
    _log = open(LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log


def say(msg: str) -> None:
    sys.stdout.write(f"SYRAX: {msg}\n")
    sys.stdout.flush()


def die(msg: str, code: int = 1) -> "None":
    sys.stderr.write(f"SYRAX: {msg}\n")
    sys.stderr.flush()
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
    def __init__(self, name: str, cmd: List[str], cwd: Path, log):
        self.name = name
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
        self.proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=log, stderr=log, **kw)

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


def _cancel_running_task() -> None:
    """Ask the core to cancel its task first, so a restart leaves a cleanly
    cancelled task instead of an INTERRUPTED one with an UNCERTAIN operation
    (each of those waits for a human)."""
    try:
        import asyncio
        import json as _json

        import websockets  # in the backend venv, which runs this launcher

        async def go():
            async with websockets.connect(f"ws://127.0.0.1:{BACKEND_PORT}/ws", max_size=None, open_timeout=5) as ws:
                await ws.send(_json.dumps({"type": "stop"}))
                deadline = time.time() + 10
                while time.time() < deadline:
                    m = _json.loads(await asyncio.wait_for(ws.recv(), max(0.5, deadline - time.time())))
                    if m.get("type") == "state" and m.get("state") == "idle":
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


def launch(dev: bool, service: bool) -> int:
    setup(verbose=False)
    check_config()
    for port in (BACKEND_PORT, UI_PORT):
        if port_in_use(port):
            if service:  # as a login service, another running SYRAX is fine: step aside quietly
                return 0
            die(f"port {port} is already in use. Is SYRAX already running?")
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
    try:
        comps.append(Component("core", [str(venv_python()), "-m", "syrax.server"], BACKEND, log))
        comps.append(Component("ui", [npx, "next", "dev" if dev else "start", *env_ui], FRONTEND, log))
        say(f"core  : ws://127.0.0.1:{BACKEND_PORT}/ws")
        say(f"orb UI: http://localhost:{UI_PORT}")
        PID_FILE.write_text(str(os.getpid()))
        # a login start opens the UI; a restart minutes or hours later does not
        open_ui = os.getenv("SYRAX_OPEN_UI") == "1" or (service and os.getenv("SYRAX_OPEN_UI") != "0" and _uptime_s() < 600)
        started = time.time()
        while not stopping:
            time.sleep(1)
            dead = [c.name for c in comps if not c.alive()]
            if dead:
                if not stopping:
                    say(f"{dead[0]} exited, shutting down.")
                break
            if open_ui and time.time() - started < 120 and both_answer():
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

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run SYRAX (core + orb UI) on any OS.", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dev", action="store_true", help="hot-reloading dev UI")
    ap.add_argument("--setup", action="store_true", help="install what is missing and exit")
    ap.add_argument("--install-service", action="store_true", help="start SYRAX at login")
    ap.add_argument("--uninstall-service", action="store_true")
    ap.add_argument("--status", action="store_true", help="login service status")
    ap.add_argument("--gate", action="store_true", help="run the release gate and exit")
    ap.add_argument("--stop", action="store_true", help="stop the running SYRAX")
    ap.add_argument("--restart", action="store_true", help="stop, then start in the background")
    ap.add_argument("--service", action="store_true", help=argparse.SUPPRESS)  # set by the login service
    a = ap.parse_args(argv)
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
        stop()
        return start_detached()
    if a.gate:
        setup(verbose=False)
        return subprocess.run([str(venv_python()), "-m", "syrax.verify"], cwd=str(BACKEND)).returncode
    return launch(dev=a.dev, service=a.service)


if __name__ == "__main__":
    sys.exit(main())
