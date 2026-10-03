"""Keep code SYRAX runs (python_execute, and any Python it spawns) away from
the records that judge it and the keys it holds.

Live 2026-10-01: SYRAX read its journal with raw sqlite3 from python_execute
and, in a second process, wrote quality runs that closed its own objective.
The journal owner lock makes a second `Journal` read-only, but raw sqlite3 or
a plain file write would bypass it. Inside python_execute (and, through
`sitecustomize`, inside every Python process it starts):

- sqlite3.connect on a protected database opens it read-only;
- open/os.remove/os.replace/os.rename for writing a protected file raise
  PermissionError.

This is a guard rail against the paths SYRAX actually took, not a sandbox: a
shell command could still reach the files. The owner process itself never
installs it.
"""

from __future__ import annotations

import builtins
import os
from pathlib import Path
from typing import Iterable, List

import re

# Live 2026-10-01: SYRAX wrote code that terminated every process above 20 %
# memory on the owner's machine. Code SYRAX runs may not kill processes it did
# not start, power the machine off, or change system configuration.
HOST_HARM = (
    (re.compile(r"\.(terminate|kill)\s*\(|\bos\.kill\b|\bos\.killpg\b|\btaskkill\b|\bpkill\b|\bkillall\b|Stop-Process", re.I), "kills processes"),
    (re.compile(r"\b(shutdown|reboot|poweroff|hibernate)\b|ExitWindowsEx|InitiateSystemShutdown|Restart-Computer|Stop-Computer", re.I), "powers the machine off or restarts it"),
    (re.compile(r"\bwinreg\.(Delete|Set)|\breg(\.exe)?\s+(delete|add)\b|\b(bcdedit|vssadmin|diskpart|netsh|schtasks|sc\s+(delete|config|stop))\b", re.I), "changes system configuration"),
)
COMMAND_KILL = re.compile(r"\btaskkill\b|\bpkill\b|\bkillall\b|\bkill\s+-|Stop-Process|\bwmic\b[^\n]*\bdelete\b", re.I)

# Shared with skills.py (unsafe skills) and permissions.py (risk levels), so
# one list decides what counts as destructive, external or system-level code.
TREE_DELETE = (re.compile(r"\bshutil\.rmtree\b|\brm\s+-rf?\b|\brmdir\s+/s\b|\bdel\s+/[sfq]\b|Remove-Item[^\n]*-Recurse|\bformat\s+[a-z]:", re.I), "deletes directory trees or disks")
FILE_DELETE = (re.compile(r"\bos\.(remove|unlink|rmdir|removedirs)\b|\.unlink\(|\.rmdir\(|\bsend2trash\b|\b(del|erase|rm|Remove-Item)\s+[\"'A-Za-z\\/.~$%-]", re.I), "deletes files")
GIT_FORCE = (re.compile(r"\bgit\b[^\n]*\b(push[^\n]*(-f\b|--force)|reset\s+--hard|clean\s+-[a-z]*[fdx]|branch\s+-D|checkout\s+--\s)", re.I), "rewrites or discards git history")
DESTRUCTIVE_PATTERNS = (TREE_DELETE, FILE_DELETE, GIT_FORCE)
NET_SEND = (re.compile(r"\bsmtplib\b|\bsendmail\b|\bftplib\b|\b(twilio|telethon|discord|slack_sdk|stripe|paypal)\b|\bwebhook\b", re.I), "sends messages or money")
NET_READ = (re.compile(r"\brequests\.|\b(?:import|from)\s+(?:requests|httpx|aiohttp|urllib\.request|websockets?)\b|\bhttpx\b|\burllib\.request\b|\baiohttp\b|\bsocket\.(socket|create_connection)\b|\bwebsockets?\b", re.I), "contacts the network")
SHELL = (re.compile(r"\bsubprocess\.|\bos\.(system|popen|spawn\w*|exec\w*)\b|\bpexpect\b", re.I), "runs shell commands")
FILE_WRITE = re.compile(r"open\([^)]*['\"][wax+]|\.write(?:_text|_bytes)?\(|\.save\(|os\.(?:remove|unlink|rename|replace|makedirs|mkdir)|shutil\.|\.unlink\(|\.mkdir\(")


def host_harm(text: str) -> list:
    return [why for rx, why in HOST_HARM if rx.search(text or "")]


def command_harm(cmd) -> list:
    """Why a shell command would harm the host (kill, power, system config)."""
    if isinstance(cmd, (list, tuple)):
        cmd = " ".join(c if isinstance(c, str) else str(os.fspath(c)) for c in cmd)
    text = str(cmd or "")
    return [why for rx, why in ((COMMAND_KILL, "kills processes"), *HOST_HARM[1:]) if rx.search(text)]


ENV = "SYRAX_GUARD_PATHS"
SITE_DIR = str(Path(__file__).with_name("_guard_site"))
WRITE_FLAGS = ("w", "a", "+", "x")


def protected_paths() -> List[str]:
    """The files code run by SYRAX must not write: the journal and its
    sidecars, and the brain keys."""
    from syrax.journal import DEFAULT_FILE

    journal = Path(os.getenv("SYRAX_JOURNAL_FILE", str(DEFAULT_FILE))).resolve()
    keys = {str((journal.parent / "brains.json").resolve())}
    if os.getenv("SYRAX_BRAINS_FILE"):
        keys.add(str(Path(os.environ["SYRAX_BRAINS_FILE"]).resolve()))
    return [str(journal), f"{journal}-wal", f"{journal}-shm", f"{journal}.owner", *sorted(keys)]


def _norm(p) -> str:
    try:
        s = os.fspath(p)
    except TypeError:
        return ""
    if isinstance(s, bytes):
        s = s.decode(errors="replace")
    if s.startswith("file:"):
        s = s[5:].split("?", 1)[0]
    try:
        return os.path.normcase(str(Path(s).resolve()))
    except (OSError, ValueError):
        return os.path.normcase(s)


def install(paths: Iterable[str]) -> None:
    """Patch this interpreter. Idempotent."""
    guarded = {os.path.normcase(str(Path(p).resolve())) for p in paths if p}
    if not guarded or getattr(builtins, "_syrax_guard", False):
        return
    builtins._syrax_guard = True

    def is_protected(p) -> bool:
        return _norm(p) in guarded

    import sqlite3

    real_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        if is_protected(database):
            kwargs["uri"] = True
            database = f"file:{Path(_norm(database)).as_posix()}?mode=ro"
        return real_connect(database, *args, **kwargs)

    sqlite3.connect = connect

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if isinstance(mode, str) and any(f in mode for f in WRITE_FLAGS) and is_protected(file):
            raise PermissionError(f"{file}: SYRAX's journal and keys are written only by the running core")
        return real_open(file, mode, *args, **kwargs)

    builtins.open = guarded_open
    import io

    io.open = guarded_open

    for name in ("remove", "unlink", "replace", "rename"):
        real = getattr(os, name)

        def make(real=real, name=name):
            def wrapped(src, *args, **kwargs):
                targets = [src] + [a for a in args[:1]]
                if any(is_protected(t) for t in targets):
                    raise PermissionError(f"{src}: SYRAX's journal and keys cannot be {name}d from here")
                return real(src, *args, **kwargs)
            return wrapped

        setattr(os, name, make())

    _guard_host()


def _guard_host() -> None:
    """Processes it did not start, the power state and system configuration
    are off limits to code SYRAX runs."""
    me = os.getpid()

    def own(pid: int) -> bool:
        if pid == me:
            return True
        try:
            import psutil

            return any(c.pid == pid for c in psutil.Process(me).children(recursive=True))
        except Exception:
            return False

    real_kill = os.kill

    def kill(pid, sig, *a, **k):
        if sig != 0 and not own(int(pid)):
            raise PermissionError(f"pid {pid}: code run by SYRAX may not kill processes it did not start")
        return real_kill(pid, sig, *a, **k)

    os.kill = kill
    if hasattr(os, "killpg"):
        def killpg(*a, **k):
            raise PermissionError("code run by SYRAX may not kill process groups")
        os.killpg = killpg

    import subprocess

    real_init = subprocess.Popen.__init__

    def popen_init(self, args, *a, **k):
        harm = command_harm(args)
        if harm:
            raise PermissionError(f"refused: this command {'; '.join(harm)}. SYRAX must not harm the host; ask the human")
        return real_init(self, args, *a, **k)

    subprocess.Popen.__init__ = popen_init
    real_system = os.system

    def system(cmd):
        harm = command_harm(cmd)
        if harm:
            raise PermissionError(f"refused: this command {'; '.join(harm)}. SYRAX must not harm the host; ask the human")
        return real_system(cmd)

    os.system = system
    try:
        import psutil
    except Exception:
        return
    for name in ("terminate", "kill", "send_signal", "suspend"):
        real = getattr(psutil.Process, name)

        def make(real=real, name=name):
            def wrapped(self, *a, **k):
                if not own(self.pid):
                    raise PermissionError(f"pid {self.pid}: code run by SYRAX may not {name} processes it did not start")
                return real(self, *a, **k)
            return wrapped

        setattr(psutil.Process, name, make())


def child_env(paths: Iterable[str]) -> None:
    """Make Python processes started from here install the guard too."""
    os.environ[ENV] = os.pathsep.join(paths)
    pp = os.environ.get("PYTHONPATH", "")
    if SITE_DIR not in pp.split(os.pathsep):
        os.environ["PYTHONPATH"] = SITE_DIR + (os.pathsep + pp if pp else "")
