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
from typing import Iterable, List, Optional, Tuple

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

# Live 2026-10-25 (audit): the gate (permissions.py), this guard, the release gate (devloop.py, verify.py) and
# the evidence (journal.py) are modules of the server process. Code that assigns to their attributes, setattr()s
# them, swaps them in sys.modules or reloads them weakens SYRAX's own guard from the inside: python_execute runs
# in a child and cannot reach the server's modules, a skill runs in the server process and could. One list for
# skills.UNSAFE (such a skill is refused before its tests run) and permissions.level_of_source (refused for every
# task kind, like HOST_HARM). Reading them (print(permissions.JUDGES)) is fine. A determined program can still
# reach a module through a computed name (importlib.import_module("syr" + "ax.guard"), a loop over sys.modules):
# these are the shapes a model writes; devloop.JUDGES keeps a released weakening out.
WEAKENS_GUARD_WHY = "weakens SYRAX's own guard; a human changes the guard, by hand"
_GUARD_MODS = r"(?:permissions|guard|devloop|journal|verify)"
_GUARD_MOD = rf"(?<![\w.])(?:syrax\.)?{_GUARD_MODS}"  # `permissions` or `syrax.permissions`, not `self.journal`
_NAMES_SYRAX = r"(?s)\A(?=.*\bsyrax\b).*?"  # only code that names syrax (an import, sys.modules) can reach its modules
_ATTR = r"(?:[A-Z][A-Z0-9_]*|[a-z_]\w*)\b"  # a constant (JUDGES) or a function (decide); not a class in an annotation
_SET = r"\s*(?:\[[^\]\n]*\]\s*)?(?:=(?!=)|[-+*/|&^%]=)"  # `= x`, `+= x`, `["k"] = x`
_MUTATES = r"[A-Z][A-Z0-9_]*\.(?:clear|pop|popitem|update|setdefault|append|extend|insert|remove)\("  # DECLARED.clear()
_PATCHERS = r"(?:setattr|delattr|patch(?:\.object)?|reload)"


def _weakening(mod: str) -> str:
    """The weakening shapes on a module named by the regex ``mod``: an assignment to an attribute or into one,
    a mutation of a constant, declare()/undeclare(), __dict__, del, setattr/delattr/patch/reload of it."""
    return (rf"{mod}\.(?:__dict__\b|{_ATTR}{_SET}|{_MUTATES}|(?:declare|undeclare)\()"
            rf"|\bdel\s+{mod}\.\w+"
            rf"|\b{_PATCHERS}\(\s*{mod}\s*[,)]")


WEAKENS_GUARD = (
    # permissions.JUDGES = (), guard.HOST_HARM += (), devloop.JUDGES = [], permissions.decide = fake,
    # permissions.DECLARED["x"] = "READ_ONLY", del guard.HOST_HARM, setattr(permissions, "classify", f),
    # monkeypatch.setattr(verify, "run_gates", f), patch.object(guard, "host_harm"), importlib.reload(syrax.permissions)
    (re.compile(_NAMES_SYRAX + "(?:" + _weakening(_GUARD_MOD) + ")"), WEAKENS_GUARD_WHY),
    # the same by the module's dotted name: setattr("syrax.permissions.decide", f), patch("syrax.guard.host_harm"),
    # sys.modules["syrax.permissions"] = fake, del sys.modules["syrax.devloop"], patch.dict(sys.modules, {"syrax.journal": m})
    (re.compile(rf"\b{_PATCHERS}\(\s*['\"]syrax\.{_GUARD_MODS}\b|\bsys\.modules\b[^\n]*['\"]syrax\.{_GUARD_MODS}['\"]"), WEAKENS_GUARD_WHY),
    # the same through an alias: from syrax import permissions as P / import syrax.guard as g; P.JUDGES = (), setattr(g, ...), reload(P)
    (re.compile(rf"(?s)(?:from\s+syrax\s+import\s+[^\n]*?\b{_GUARD_MODS}\s+as\s+(\w+)|import\s+syrax\.{_GUARD_MODS}\s+as\s+(\w+))\b.*?"
                + "(?:" + _weakening(r"(?<![\w.])(?:\1|\2)") + ")"), WEAKENS_GUARD_WHY),
)

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


# Live 2026-10-27 (audit): SYRAX could drive its own control interface as if it were the human. python_execute code
# that opens ws://127.0.0.1:8765/ws (or requests/urllib/httpx to it) was only EXTERNAL_READ, and a browser call could
# open the HUD (http://127.0.0.1:8765/hud/) or the UI, whose Origin the core trusts in full (auth.verdict). Through /ws
# it could start a task authorized by its own words, force-resume, forget memories, close its own objectives, save
# brains, change autonomy, enable skills. Code and browser calls that target the core's host:port, its UI's or an
# allowed origin are refused for every task kind, like HOST_HARM; the runtime guard (_guard_core_socket) refuses a
# python child's connect to the core's port, also when the code computes the address.
SELF_CONTROL_WHY = ("would control SYRAX itself through its own interface (the core's port, its HUD or UI page); "
                    "only the human drives SYRAX's controls")
CORE_PORT = 8765
UI_PORT = 3000
CORE_PATHS = ("ws", "live", "token", "self", "voice", "stt", "upload", "hud")
_LOOPBACK_RX = r"127(?:\.\d{1,3}){3}|localhost|\[::1\]|::1|0\.0\.0\.0|\[::\]"
_LOOPBACK_ANY = re.compile(rf"(?<![\w.:-])(?:{_LOOPBACK_RX})(?![\w-])", re.I)
_CORE_PATHS_RX = "|".join(CORE_PATHS)


def _int(value, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _origins() -> List[Tuple[str, Optional[int]]]:
    """(host, port) of every Origin the core trusts besides its own (SYRAX_ALLOWED_ORIGINS, server.py's default)."""
    out = []
    for o in os.getenv("SYRAX_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","):
        m = re.match(r"^\s*[a-z][\w+.-]*://(\[[^\]]+\]|[^/:\s]+)(?::(\d+))?", o, re.I)
        if m:
            out.append((m.group(1).lower(), _int(m.group(2))))
    return out


def core_ports() -> set:
    """The ports of the core itself: the default and SYRAX_PORT."""
    return {CORE_PORT, _int(os.getenv("SYRAX_PORT"), CORE_PORT)}


def self_ports() -> set:
    """The core's ports and its UI's (SYRAX_UI_PORT, the ports of the allowed origins): a page there is trusted."""
    ports = core_ports() | {_int(os.getenv("SYRAX_UI_PORT"), UI_PORT)}
    return ports | {p for _, p in _origins() if p}


def _self_rx() -> "re.Pattern[str]":
    hosts = [_LOOPBACK_RX]
    extra = {h for h, _ in _origins()} | {os.getenv("SYRAX_HOST", "127.0.0.1").strip().lower()}
    hosts += [re.escape(h) for h in sorted(extra) if h]
    host = rf"(?<![\w.-])(?:{'|'.join(hosts)})\]?"
    port = "|".join(str(p) for p in sorted(self_ports()))
    core = "|".join(str(p) for p in sorted(core_ports()))
    return re.compile(
        rf"{host}:(?:{port})(?!\d)"  # 127.0.0.1:8765, localhost:3000, [::1]:8765
        rf"|{host}:\{{[^}}\n]*\}}/(?:{_CORE_PATHS_RX})\b"  # f"ws://localhost:{port}/ws"
        rf"|{host}:['\"]\s*\+[^\n]*?['\"]/(?:{_CORE_PATHS_RX})\b"  # "http://localhost:" + str(p) + "/token"
        rf"|(?s:\A(?=.*?{host}).*?(?:(?<![\w.]){'(?:' + core + ')'}(?![\w.])|\bSYRAX_PORT\b))",  # ("127.0.0.1", 8765), getenv("SYRAX_PORT")
        re.I)


def controls_self(text: str) -> list:
    """[SELF_CONTROL_WHY] when code or a browser call targets the core's own host:port (or its UI's)."""
    text = text or ""
    if not _LOOPBACK_ANY.search(text) and not any(h in text.lower() for h, _ in _origins()):
        return []
    return [SELF_CONTROL_WHY] if _self_rx().search(text) else []


def weakens_guard(text: str) -> list:
    """[WEAKENS_GUARD_WHY] when the code assigns to, patches, swaps or reloads SYRAX's gate and guard modules."""
    text = text or ""
    return [WEAKENS_GUARD_WHY] if any(rx.search(text) for rx, _ in WEAKENS_GUARD) else []


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
    return [str(journal), f"{journal}-wal", f"{journal}-shm", f"{journal}.owner", *sorted(keys), *isolation_rules()]


def isolation_rules() -> List[str]:
    """While an autonomous task works in its own worktree (M1), the running
    tree is read-only for the code it runs: "<folder>*" makes a folder
    read-only, "!<folder>*" re-opens a part of it. The workspace and the
    worktrees (.syrax) stay writable. The editor already writes into the
    worktree; this closes the python_execute way around it."""
    try:
        from syrax import editor

        mapping = editor.ROOT_MAP
    except Exception:
        return []
    if not mapping:
        return []
    live = Path(mapping[0]).resolve()
    return [f"{live}{os.sep}*", f"!{live / 'backend' / 'workspace'}{os.sep}*", f"!{live / '.syrax'}{os.sep}*"]


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


def _rules(paths: Iterable[str]):
    """Split the path list into exact files, read-only folders and their re-opened parts."""
    files, readonly, allowed = set(), [], []
    for p in paths:
        if not p:
            continue
        if p.endswith("*"):
            folder = os.path.normcase(str(Path(p.lstrip("!")[:-1]).resolve()))
            (allowed if p.startswith("!") else readonly).append(folder)
        else:
            files.add(os.path.normcase(str(Path(p).resolve())))
    return files, readonly, allowed


def _under(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def install(paths: Iterable[str]) -> None:
    """Patch this interpreter. Idempotent."""
    guarded, readonly, allowed = _rules(paths)
    if not (guarded or readonly) or getattr(builtins, "_syrax_guard", False):
        return
    builtins._syrax_guard = True

    def in_readonly_tree(p) -> bool:
        n = _norm(p)
        return bool(n) and any(_under(n, f) for f in readonly) and not any(_under(n, a) for a in allowed)

    def is_protected(p) -> bool:
        return _norm(p) in guarded

    def refuse_write(p) -> Optional[str]:
        if is_protected(p):
            return f"{p}: SYRAX's journal and keys are written only by the running core"
        if in_readonly_tree(p):
            return (f"{p}: the running SYRAX is read-only while this task works in its own worktree; "
                    "write into the worktree (.syrax/worktrees/...) or backend/workspace, and `release` lands the change")
        return None

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
        if isinstance(mode, str) and any(f in mode for f in WRITE_FLAGS):
            why = refuse_write(file)
            if why:
                raise PermissionError(why)
        return real_open(file, mode, *args, **kwargs)

    builtins.open = guarded_open
    import io

    io.open = guarded_open

    for name in ("remove", "unlink", "replace", "rename", "rmdir"):
        real = getattr(os, name)

        def make(real=real, name=name):
            def wrapped(src, *args, **kwargs):
                targets = [src] + [a for a in args[:1]]
                if any(is_protected(t) for t in targets):
                    raise PermissionError(f"{src}: SYRAX's journal and keys cannot be {name}d from here")
                for t in targets:
                    why = refuse_write(t)
                    if why:
                        raise PermissionError(why)
                return real(src, *args, **kwargs)
            return wrapped

        setattr(os, name, make())

    _guard_core_socket()
    _guard_host()


def refuses_connect(address) -> Optional[str]:
    """Why a socket connect to ``address`` is refused: it is the core's own port on this machine."""
    if not isinstance(address, tuple) or len(address) < 2:
        return None
    port = _int(address[1])
    if port not in core_ports():
        return None
    host = address[0].decode(errors="replace") if isinstance(address[0], bytes) else str(address[0])
    host = host.strip().strip("[]").split("%", 1)[0].lower()
    if host in ("", "localhost", os.getenv("SYRAX_HOST", "127.0.0.1").strip().lower()):
        return SELF_CONTROL_WHY
    import ipaddress

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    mapped = getattr(ip, "ipv4_mapped", None)
    if ip.is_loopback or ip.is_unspecified or (mapped is not None and mapped.is_loopback):
        return SELF_CONTROL_WHY
    return None


def _guard_core_socket() -> None:
    """A Python child of SYRAX may not connect to the core's own port: the static check (controls_self) sees the
    literal shapes, this sees the address the code computed. socket.connect/connect_ex (create_connection, the
    selector event loop) and the Windows proactor's connect (asyncio, websockets) are the ways in."""
    import socket

    def refuse(address):
        why = refuses_connect(address)
        if why:
            raise PermissionError(f"refused: {address!r}: the code {why}")

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def connect(self, address, *a, **k):
        refuse(address)
        return real_connect(self, address, *a, **k)

    def connect_ex(self, address, *a, **k):
        refuse(address)
        return real_connect_ex(self, address, *a, **k)

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
    try:
        from asyncio import windows_events
    except Exception:  # not Windows
        return
    proactor = getattr(windows_events, "IocpProactor", None)
    if proactor is not None and hasattr(proactor, "connect"):
        real_proactor_connect = proactor.connect

        def proactor_connect(self, conn, address, *a, **k):
            refuse(address)
            return real_proactor_connect(self, conn, address, *a, **k)

        proactor.connect = proactor_connect


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
