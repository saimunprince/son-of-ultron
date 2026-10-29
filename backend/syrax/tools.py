import asyncio
from typing import Awaitable, Callable, Optional

from pydantic import Field

from app.tool.base import BaseTool

Emit = Callable[[dict], Awaitable[None]]


UNATTENDED_ANSWER = (
    "Nobody will answer: this is an unattended run. Decide yourself: do exactly what the request named, "
    "refuse what it did not name, and say in the final answer what you did and did not do."
)


class WebAskHuman(BaseTool):
    """ask_human replacement: asks the human through the SYRAX UI instead of stdin."""

    name: str = "ask_human"
    description: str = (
        "Ask the human operator a question and wait for the answer. "
        "Use only when you are genuinely blocked on a decision only they can make."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "inquire": {
                "type": "string",
                "description": "The question for the human.",
            }
        },
        "required": ["inquire"],
    }

    emit: Optional[Emit] = Field(default=None, exclude=True)
    timeout: float = 600.0
    pending: Optional[asyncio.Future] = Field(default=None, exclude=True)
    # Live 2026-10-14 (quality run #35, guard_broad_delete): an eval task asked the human, a UI was
    # connected, and the question hung until the case timed out. An evaluation is unattended by
    # definition: the console answers at once, and the answer is journaled like any other.
    unattended: bool = False

    async def execute(self, inquire: str) -> str:
        if self.unattended:
            return UNATTENDED_ANSWER
        if self.emit is None:
            return "No operator connected. Proceed with your best judgement."
        loop = asyncio.get_running_loop()
        self.pending = loop.create_future()
        await self.emit({"type": "ask", "question": inquire})
        try:
            answer = await asyncio.wait_for(self.pending, timeout=self.timeout)
        except asyncio.TimeoutError:
            return "The human did not answer in time. Proceed with your best judgement."
        finally:
            self.pending = None
        return str(answer).strip() or "(no answer)"

    def answer(self, text: str) -> bool:
        if self.pending is not None and not self.pending.done():
            self.pending.set_result(text)
            return True
        return False


import os  # noqa: E402
import signal  # noqa: E402
import sys  # noqa: E402
import multiprocessing  # noqa: E402
import threading  # noqa: E402

# Workers that run model-written code are always SPAWNED, never forked (audit 2026-10-28). Linux defaulted to fork: the
# worker was a copy of the server, with the journal's read-write connection, the listening socket and the brain keys
# in memory, none of which the guard (which wraps new opens) could see. Windows always spawned; now every OS does.


def ensure_venv_on_path() -> None:
    """Put the interpreter's own bin folder first on PATH, for every program this process starts. Live 2026-10-29 (first
    Linux quality runs): code the brain wrote called `python` and `pytest` by name eight times and got "No such file
    or directory": Ubuntu has only python3, and the launcher runs the venv's python without activating the venv (on
    Windows `python` was on PATH). The venv's bin holds python, pytest and the rest of SYRAX's tools."""
    bindir = os.path.dirname(os.path.abspath(sys.executable))
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if bindir not in parts:
        os.environ["PATH"] = os.pathsep.join([bindir, *[p for p in parts if p]])


ensure_venv_on_path()


def ensure_spawn() -> None:
    """Make spawn the start method of this process (checked before every worker start: nothing may switch it back)."""
    if multiprocessing.get_start_method(allow_none=True) != "spawn":
        multiprocessing.set_start_method("spawn", force=True)


ensure_spawn()

# What kind of task is running (core._begin_now sets it): SYRAX's own work ("autonomous") gets a kernel write
# boundary around its code; a human's request keeps the reach the human gave it (home, desktop) minus the secrets
# (human_boundary, since 2026-10-29).
TASK_KIND: Optional[str] = None
WRITE_ROOTS: tuple = ()  # extra writable roots for the running task (its isolation worktree)
CONFINED_KINDS = ("autonomous",)


OWN_TCP_PORTS = tuple(int(p) for p in os.getenv("SYRAX_OWN_TCP_PORTS", "80,443,53").split(",") if p.strip())
SYSTEM_READ = ("/usr", "/lib", "/lib64", "/lib32", "/bin", "/sbin", "/etc", "/proc", "/sys", "/dev", "/run", "/opt",
               "/snap", "/var")
HOME_READ = (".gitconfig", ".config/git")  # git refuses to run when it cannot read its config
SEALED = ("backend/config",)  # the brain keys, the journal, the UI token, the backups' manifests
# Files in a sealed folder own code may still read. Live 2026-10-29 (autonomy, level 3): the flight_search skill loads
# app.config, which reads config.toml, and failed "Permission denied"; the file holds OpenManus' boot settings with a
# placeholder key ("managed-by-syrax"; the brains' keys are in brains.json), and writing it stays refused.
UNSEALED = ("backend/config/config.toml",)


def read_roots(repo: Optional[str] = None) -> list:
    """What SYRAX's own code may read (2026-10-29): the system, the interpreter and venv, harmless git config, and
    the live repository except backend/config. Landlock grants whole trees, so the repository is granted entry by
    entry, and backend entry by entry, leaving the sealed folder out."""
    from pathlib import Path

    from syrax.journal import BACKEND_ROOT

    root = Path(repo) if repo else BACKEND_ROOT.parent
    out = [p for p in SYSTEM_READ if os.path.exists(p)]
    out += sorted({sys.prefix, sys.base_prefix, os.path.dirname(os.path.dirname(os.path.realpath(sys.executable)))})
    home = Path.home()
    out += [str(home / h) for h in HOME_READ if (home / h).exists()]
    sealed = {(root / s).resolve() for s in SEALED}

    def walk(d: Path) -> None:
        for entry in sorted(d.iterdir()):
            r = entry.resolve()
            if r in sealed:
                continue
            if any(s.is_relative_to(r) for s in sealed):
                walk(entry)  # an ancestor of a sealed folder: grant its other entries one by one
            else:
                out.append(str(entry))

    walk(root)
    out += [str(root / f) for f in UNSEALED if (root / f).is_file()]
    return out


def list_roots(repo: Optional[str] = None) -> list:
    """Folders own code may list but not read inside: the repository root and every folder down to a sealed one
    (import finders list each sys.path folder, backend among them; names in backend/config show, contents do not)."""
    from pathlib import Path

    from syrax.journal import BACKEND_ROOT

    root = Path(repo) if repo else BACKEND_ROOT.parent
    out = []
    for s in SEALED:
        d = root / s
        while True:
            out.append(str(d))
            if d == root:
                break
            d = d.parent
    return sorted(set(out))


# A human's request (Prince, 2026-10-29: "your python_execute too"): its code keeps the reach the human gave it (the
# home folders, the desktop, the web, local ports) and loses what an injected instruction would go for. It reads the
# system and home except the secrets (HUMAN_SECRETS, backend/config); it writes the home's ordinary folders, /tmp and
# the workspace, never a dotfile (a shell rc or an autostart entry would run injected code again later), the
# repository's .git (hooks) or its isolation worktrees. Landlock grants whole
# trees, so a folder holding a sealed one is granted entry by entry (_grant), and an entry whose real path is or lies
# in a sealed folder (a symlink to ~/.ssh) is never granted.
HUMAN_SECRETS = (".ssh", ".gnupg", ".claude", ".aws", ".azure", ".kube", ".docker", ".password-store", ".pki",
                 ".netrc", ".git-credentials", ".pgpass", ".config/gh", ".config/gcloud", ".local/share/keyrings",
                 ".mozilla", ".config/google-chrome", ".config/chromium", ".config/BraveSoftware")
HUMAN_WRITE_DOT = (".cache",)  # the one dot folder a human's code writes: pip, matplotlib and model caches
OTHER_READ = ("/media", "/mnt", "/srv")
HUMAN_TMP = ("/tmp",)  # read and written whole: a human asks for /tmp/x.png


def _grant(root, sealed: set) -> list:
    """The entries under `root` minus the `sealed` real paths: an ancestor of a sealed path is walked into, anything
    else is granted whole; an entry that is, or resolves into, a sealed path is left out."""
    out = []

    def walk(d) -> None:
        try:
            entries = sorted(d.iterdir())
        except OSError:
            return
        for entry in entries:
            try:
                real = entry.resolve()
            except OSError:
                continue
            if any(real == s or real.is_relative_to(s) for s in sealed):
                continue
            if any(s.is_relative_to(real) for s in sealed):
                walk(entry)
            else:
                out.append(str(entry))

    walk(root)
    return out


def _repositories(repo) -> list:
    """`repo` and, when it is a git worktree (a `.git` file "gitdir: <main>/.git/worktrees/<name>"), the main
    repository it belongs to: a gate or a test runs from a worktree, and the live keys sit in the main one."""
    from pathlib import Path

    out = [repo]
    try:
        line = (repo / ".git").read_text(encoding="utf-8").strip()
    except OSError:
        return out
    if line.startswith("gitdir:"):
        gitdir = Path(line[len("gitdir:"):].strip())
        if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
            out.append(gitdir.parent.parent.parent)
    return out

def human_boundary(tmpdir: str, out_path: str) -> dict:
    """The Landlock spec of a human's python_execute and skill calls (HUMAN_SECRETS, _grant)."""
    from pathlib import Path

    from app.config import config
    from syrax.journal import BACKEND_ROOT

    home, repo = Path.home(), BACKEND_ROOT.parent
    repos = _repositories(repo)
    secrets = {(home / s).resolve() for s in HUMAN_SECRETS} | {(r / s).resolve() for r in repos for s in SEALED}
    dots = {e.resolve() for e in home.iterdir() if e.name.startswith(".") and e.name not in HUMAN_WRITE_DOT} if home.is_dir() else set()
    no_write = secrets | dots | {(r / d).resolve() for r in repos for d in (".git", ".syrax")}
    readable = [p for p in (*SYSTEM_READ, *OTHER_READ, *HUMAN_TMP) if os.path.exists(p)]
    readable += sorted({sys.prefix, sys.base_prefix, os.path.dirname(os.path.dirname(os.path.realpath(sys.executable)))})
    readable += _grant(home, secrets) + _grant(repo, secrets) + [str(repo / f) for f in UNSEALED if (repo / f).is_file()]
    writable = [str(config.workspace_root), *map(str, WRITE_ROOTS), tmpdir, out_path, *HUMAN_TMP, "/dev/null", "/dev/shm"]
    writable += _grant(home, no_write) + _grant(repo, no_write)  # the repository wherever it lies, minus its .git
    return {"readable": readable, "writable": writable, "listable": sorted({str(home), *list_roots()})}


def confinement(kind: Optional[str], out_path: str, tmpdir: str, timeout: int) -> dict:
    """The OS confinement spec a python_execute worker applies before it runs (syrax._confine.apply)."""
    spec = {
        "cpu_s": int(timeout) * max(1, os.cpu_count() or 1) + 10,  # CPU seconds summed over threads: a backstop
        "memory_mb": int(os.getenv("SYRAX_PYEXEC_MEMORY_MB", "8192")),
        "file_mb": int(os.getenv("SYRAX_PYEXEC_FILE_MB", "2048")),
        "tmpdir": tmpdir,
    }
    if kind in CONFINED_KINDS:
        from app.config import config

        spec["writable"] = [str(config.workspace_root), *map(str, WRITE_ROOTS), tmpdir, out_path, "/dev/null", "/dev/shm"]
        spec["readable"], spec["listable"] = read_roots(), list_roots()
        spec["scrub_env"] = True  # no credentials, agents or session bus for own code (2026-10-29)
        # TCP only to the web and DNS, no listening port: own code cannot drive the core (8765), the UI (3000), the
        # browser's debug port, the local model (11434) or ssh, at the kernel (2026-10-29; Landlock ABI 4+)
        spec["tcp_connect"] = list(OWN_TCP_PORTS)
        spec["require_landlock"] = sys.platform.startswith("linux")  # fail closed where the kernel boundary exists
    elif sys.platform.startswith("linux"):
        # a human's request: its reach minus the secrets (HUMAN_SECRETS). Its environment stays whole: the human may
        # hand a key to their own script (test_env_secrets), and the session bus opens apps and notifications
        spec.update(human_boundary(tmpdir, out_path))
        spec["require_landlock"] = True
    return spec

# Windows starts a worker by spawning a fresh interpreter, and spawn re-imports the parent's __main__ module first
# when it has a module spec or a file (multiprocessing.spawn.get_preparation_data). Live, __main__ is syrax.server
# (`python -m syrax.server`): every python_execute worker imported the whole server, FastAPI and the agent before
# running one line. Measured 2026-10-27 with a server-like __main__: 2.59-2.74 s per call as it was, 0.13-0.20 s with
# __main__ hidden during the start; the live journal's median short call was 2.9-3.3 s. The worker's target lives in
# _pyexec_child (stdlib only) and needs nothing from __main__.
_MAIN_LOCK = threading.Lock()


def start_without_main(proc) -> None:
    """proc.start() with __main__'s __spec__ and __file__ hidden for the moment the spawn data is taken, so the
    child does not re-import the parent's main module; both are put back however the start ends."""
    main = sys.modules.get("__main__")
    with _MAIN_LOCK:
        saved = {k: getattr(main, k) for k in ("__spec__", "__file__") if main is not None and hasattr(main, k)}
        try:
            if main is not None:
                main.__spec__ = None
                if "__file__" in saved:
                    del main.__file__
            proc.start()
        finally:
            for k, v in saved.items():
                setattr(main, k, v)
            if main is not None and "__spec__" not in saved and hasattr(main, "__spec__"):
                del main.__spec__
import time  # noqa: E402
from typing import Dict  # noqa: E402

from app.tool.python_execute import PythonExecute  # noqa: E402
from syrax._pyexec_child import PRELOADED, _PrintedOutput, _utf8_by_default, guarded_run, run_code  # noqa: E402,F401


START_TIMEOUT_S = 30.0  # starting a worker normally takes well under a second


def _poll(conn, timeout: float = 0.0) -> bool:
    """True when the worker sent something or its end is gone; on Windows a
    closed pipe raises BrokenPipeError from poll() instead of reporting EOF."""
    try:
        return conn.poll(timeout)
    except (EOFError, OSError):
        return True


def _printed_before(path: str, limit: int = 2000) -> str:
    """The tail of what a stopped code printed, or "" when it printed nothing."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return ""
    return text if len(text) <= limit else "…" + text[-limit:]


def _remove_quietly(path: str) -> None:
    import os

    try:
        os.remove(path)
    except OSError:
        pass


def _worker_descendants(proc) -> Optional[list]:
    """psutil handles of everything the worker started (children of children too), taken while it is alive; only
    when the worker really is this process's child (a fake or a reused pid never names a tree). None without psutil."""
    try:
        import psutil
    except Exception:
        return None
    import os

    try:
        p = psutil.Process(proc.pid)
        if p.ppid() != os.getpid():
            return []
        return p.children(recursive=True)
    except Exception:
        return []


def _kill_quietly(proc, tree: bool = True) -> None:
    """Kill the worker and, with `tree`, everything it started. 2026-10-27 review: only the worker was killed on a
    timeout or an abort, and on Windows its children (a subprocess pytest, a Popen'd server) ran on with nobody
    waiting for them. The tree is read before the worker dies (after, its children have no parent to be found by);
    without psutil, Windows' taskkill /T takes the tree. On POSIX the worker leads a process group of its own
    (syrax._confine.own_group), and the group dies with one killpg: no psutil needed (this Linux machine had none,
    2026-10-28, and only the worker died), and a child whose parent already exited is still in the group."""
    try:
        if proc.pid is None or not proc.is_alive():
            return
        if tree and hasattr(os, "killpg") and isinstance(proc, multiprocessing.process.BaseProcess):
            try:
                # only a group the worker leads: before its setsid it is still in the server's group, and that
                # group must never be killed
                if os.getpgid(proc.pid) == proc.pid:
                    os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        kids = _worker_descendants(proc) if tree else []
        if kids is None and sys.platform == "win32" and isinstance(proc, multiprocessing.process.BaseProcess):
            import subprocess

            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                pass
        proc.kill()
        proc.join(1)
        for k in kids or []:
            try:
                k.kill()
            except Exception:
                pass
        if kids:
            import psutil

            psutil.wait_procs(kids, timeout=2)
    except Exception:
        pass


class AsyncPythonExecute(PythonExecute):
    """python_execute that does not freeze the event loop.

    Upstream calls the blocking ``proc.join(timeout)`` inside an async method,
    which stalls the whole server (no streaming, no abort) while code runs.
    This version polls the child process asynchronously, kills it when the
    task is aborted, and allows a longer default timeout for real work.
    """

    parameters: dict = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute. Only print() output is visible. Every call starts "
                               "fresh: nothing defined in an earlier call exists. os, sys, json, re, math, time, "
                               "datetime, shutil, subprocess, glob, pathlib and Path are already imported.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to run (default 60, max 600).",
            },
        },
        "required": ["code"],
    }

    def _guarded_run(self, code: str, conn, safe_globals: dict, paths: list, out_path: Optional[str] = None) -> None:
        """The worker's entry, kept for callers; the worker itself runs syrax._pyexec_child.guarded_run, which
        imports only the standard library and the guard (this module would load app.tool and pydantic in it)."""
        guarded_run(code, conn, safe_globals, paths, out_path)

    def _run_code(self, code: str, result_dict: dict, safe_globals: dict, out_path: Optional[str] = None) -> None:
        run_code(code, result_dict, safe_globals, out_path)

    async def execute(self, code: str, timeout: int = 60) -> Dict:
        """One worker process and a pipe; nothing here blocks the event loop.

        Live 2026-10-10: this used multiprocessing.Manager(), whose start waits
        synchronously for a second process to report back. That process died
        at start, the wait never ended, and the whole server froze for 20
        minutes (no HTTP, no abort) with an UNCERTAIN task. Now the worker is
        started in a thread with a deadline, and a worker that dies without a
        result is reported instead of waited for."""
        timeout = max(1, min(int(timeout or 60), 600))
        if isinstance(__builtins__, dict):
            safe_globals = {"__builtins__": __builtins__}
        else:
            safe_globals = {"__builtins__": __builtins__.__dict__.copy()}
        from syrax.guard import protected_paths

        import tempfile

        fd, out_path = tempfile.mkstemp(prefix="syrax_py_", suffix=".out")
        __import__("os").close(fd)
        tmpdir = tempfile.mkdtemp(prefix="syrax_py_tmp_")  # the worker's own TMPDIR (writable under the boundary)
        try:
            spec = confinement(TASK_KIND, out_path, tmpdir, timeout)
            return await self._execute(code, timeout, safe_globals, protected_paths(), out_path, spec)
        finally:
            _remove_quietly(out_path)
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)

    async def _execute(self, code: str, timeout: int, safe_globals: dict, paths: list, out_path: str,
                       confine: Optional[dict] = None) -> Dict:
        ensure_spawn()
        recv, send = multiprocessing.Pipe(duplex=False)
        proc = multiprocessing.Process(target=guarded_run, args=(code, send, safe_globals, paths, out_path, confine), daemon=True)
        starter = asyncio.ensure_future(asyncio.to_thread(start_without_main, proc))
        try:
            done, _ = await asyncio.wait({starter}, timeout=START_TIMEOUT_S)
        except asyncio.CancelledError:
            starter.add_done_callback(lambda _f: _kill_quietly(proc))
            raise
        if not done:  # the start is stuck; whatever it starts later is killed
            starter.add_done_callback(lambda _f: _kill_quietly(proc))
            return {"observation": f"Error: python_execute could not start a worker process within {START_TIMEOUT_S:g} s (the machine may be short of memory); nothing ran", "success": False}
        if starter.exception() is not None:
            return {"observation": f"Error: python_execute could not start a worker process: {starter.exception()}", "success": False}
        send.close()  # the child holds its own end; EOF once it is gone
        result = None
        eof = False  # the worker's end closed without a result: it is exiting, not running
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if _poll(recv):
                    try:
                        result = recv.recv()
                    except (EOFError, OSError):
                        eof = True
                    break
                if not proc.is_alive():
                    if _poll(recv, 0.2):  # sent just before it exited
                        try:
                            result = recv.recv()
                        except (EOFError, OSError):
                            eof = True
                    break
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            _kill_quietly(proc)
            recv.close()
            raise
        recv.close()
        # the pipe can report EOF a moment before Windows has reaped the process:
        # still "alive" then is an exit in progress, not a timeout (seen under load)
        if result is None and not eof and proc.is_alive():
            await asyncio.to_thread(_kill_quietly, proc)  # the tree's wait stays off the event loop
            printed = _printed_before(out_path)
            return {
                "observation": f"Execution timeout after {timeout} seconds"
                               + (f"; it printed this before it was stopped:\n{printed}" if printed.strip() else ""),
                "success": False,
            }
        if proc.is_alive():  # it answered: what it started on purpose (a server) outlives it, as after a normal exit
            await asyncio.to_thread(proc.join, 2)
            _kill_quietly(proc, tree=False)
        if result is None:
            return {"observation": f"Error: the python_execute worker exited with code {proc.exitcode} before returning a result", "success": False}
        return dict(result)
