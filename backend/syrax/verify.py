"""SYRAX verification gate: real commands, real exit codes, journaled evidence.

GREEN means every *required* gate returned PASS. A gate that cannot run
(missing binary, timeout, crash of the runner itself) is NOT_VERIFIED, and a
required NOT_VERIFIED blocks just like a FAIL. Nothing here interprets output
optimistically: the exit code decides.

Usage:
    .venv/bin/python -m syrax.verify            # run the default gates for this repo
    .venv/bin/python -m syrax.verify --gate pytest --gate diff_scan
    .venv/bin/python -m syrax.verify --json
Exit code 0 = GREEN, 1 = BLOCKED.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from syrax.journal import BACKEND_ROOT, Journal, _git_head

REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = REPO_ROOT / "frontend"
TAIL_LINES = 40
WINDOWS = sys.platform == "win32"

GateFn = Callable[[], Tuple[bool, str]]


@dataclass
class Gate:
    name: str
    cmd: Union[Sequence[str], GateFn]
    cwd: Path = REPO_ROOT
    required: bool = True
    env: Optional[Dict[str, str]] = None
    timeout: float = 900.0
    # inherited variables with these prefixes are dropped before env applies: the
    # tests must not see this machine's local SYRAX configuration
    drop_env_prefixes: Sequence[str] = ()


@dataclass
class GateResult:
    name: str
    required: bool
    status: str  # PASS | FAIL | NOT_VERIFIED
    exit_code: Optional[int]
    duration_ms: int
    evidence: str
    command: str = ""


@dataclass
class Verification:
    status: str  # GREEN | BLOCKED
    ts: float
    git_head: Optional[str]
    gates: List[GateResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "ts": self.ts,
            "git_head": self.git_head,
            "gates": [asdict(g) for g in self.gates],
        }


def _tail(text: str, lines: int = TAIL_LINES) -> str:
    parts = text.strip().splitlines()
    return "\n".join(parts[-lines:])


SLEEP_GAP_S = 30.0  # a gate loop iteration this late means the machine was asleep


def _kill_tree(proc: "subprocess.Popen") -> None:
    """Stop a gate and everything it started (pytest runs skill tests in their own processes)."""
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=30)
        else:
            import signal

            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_gate(gate: Gate, cancel: Optional[threading.Event] = None) -> GateResult:
    """Run one gate. A command gate stops, with its whole process tree, when
    ``cancel`` is set (live 2026-10-11: a stopped task's gate pytest kept
    running for minutes inside the removed worktree)."""
    started = time.monotonic()
    if callable(gate.cmd):
        try:
            ok, evidence = gate.cmd()
            status = "PASS" if ok else "FAIL"
            code = 0 if ok else 1
        except Exception as e:  # the checker itself broke: not evidence either way
            status, code, evidence = "NOT_VERIFIED", None, f"gate crashed: {e!r}"
        return GateResult(
            gate.name, gate.required, status, code,
            int((time.monotonic() - started) * 1000), _tail(evidence), "<python>",
        )
    cmd = [str(c) for c in gate.cmd]
    inherited = {k: v for k, v in os.environ.items() if not any(k.startswith(p) for p in gate.drop_env_prefixes)}
    env = {**inherited, **(gate.env or {})}
    group = {} if WINDOWS else {"start_new_session": True}
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(gate.cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", **group,
        )
    except FileNotFoundError as e:
        return GateResult(
            gate.name, gate.required, "NOT_VERIFIED", None,
            int((time.monotonic() - started) * 1000), f"cannot start: {e}", " ".join(cmd),
        )
    deadline = started + gate.timeout
    last = time.monotonic()
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            now = time.monotonic()
            if now - last > SLEEP_GAP_S:
                # The loop wakes every half second; a longer gap is time the machine slept, not time the gate ran.
                # Live 2026-10-17: the PC slept 69 minutes during objective 274's gate, pytest was killed as a
                # "timeout after 900.0s" on wake, and a correct change was rolled back.
                deadline += now - last
            last = now
            stopped = cancel is not None and cancel.is_set()
            if stopped or time.monotonic() > deadline:
                _kill_tree(proc)
                try:
                    proc.communicate(timeout=30)
                except Exception:
                    pass
                why = "cancelled: the task was stopped" if stopped else f"timeout after {gate.timeout}s"
                return GateResult(
                    gate.name, gate.required, "NOT_VERIFIED", None,
                    int((time.monotonic() - started) * 1000), why, " ".join(cmd),
                )
    out = (stdout or "") + ("\n" + stderr if stderr else "")
    return GateResult(
        gate.name, gate.required, "PASS" if proc.returncode == 0 else "FAIL", proc.returncode,
        int((time.monotonic() - started) * 1000), _tail(out), " ".join(cmd),
    )


def run_gates(
    gates: Sequence[Gate], journal: Optional[Journal] = None, task_id: Optional[str] = None,
    cancel: Optional[threading.Event] = None, git_head: Optional[str] = None,
) -> Verification:
    """Run the gates in order. ``git_head`` is the revision the checked tree is
    based on (a task's worktree, not the running tree). A cancelled run starts
    no further gate and is not journaled: its task is gone."""
    results = []
    for g in gates:
        if cancel is not None and cancel.is_set():
            break
        results.append(run_gate(g, cancel))
    cancelled = cancel is not None and cancel.is_set()
    green = not cancelled and all(r.status == "PASS" for r in results if r.required)
    v = Verification(
        status="GREEN" if green else "BLOCKED",
        ts=time.time(),
        git_head=git_head or _git_head(REPO_ROOT),
        gates=results,
    )
    if journal is not None and not cancelled:
        journal.record_verification_sync(v.to_dict(), task_id=task_id)
    return v


# ——— diff scan: secrets, debug leftovers, junk files ———

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
]
DEBUG_PATTERNS = {
    ".py": [re.compile(r"^\s*print\("), re.compile(r"^\s*breakpoint\(\)")],
    ".ts": [re.compile(r"console\.log\("), re.compile(r"^\s*debugger\b")],
    ".tsx": [re.compile(r"console\.log\("), re.compile(r"^\s*debugger\b")],
}
JUNK_SUFFIXES = (".db", ".db-wal", ".db-shm", ".sqlite", ".log", ".tmp", ".pem", ".key")
JUNK_NAMES = (".env",)
MAX_UNTRACKED_BYTES = 5 * 1024 * 1024


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    return name.startswith("test_") or name.endswith(".test.ts") or name == "conftest.py"


def scan_diff_text(diff: str) -> List[str]:
    """Scan a unified diff for secrets and debug leftovers in ADDED lines."""
    findings: List[str] = []
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[4:].strip()
            if current.startswith("b/"):
                current = current[2:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        if any(pat.search(body) for pat in SECRET_PATTERNS):
            findings.append(f"{current}: possible secret: {body.strip()[:80]}")
        if _is_test_file(current):
            continue
        for pat in DEBUG_PATTERNS.get(Path(current).suffix, []):
            if pat.search(body):
                findings.append(f"{current}: debug leftover: {body.strip()[:80]}")
    return findings


def diff_scan(root: Path = REPO_ROOT) -> Tuple[bool, str]:
    diff = subprocess.run(
        ["git", "diff", "HEAD", "--", ".", ":(exclude)*.lock", ":(exclude)package-lock.json"],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if diff.returncode != 0:
        raise RuntimeError(f"git diff failed: {diff.stderr.strip()}")
    findings = scan_diff_text(diff.stdout)
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    ).stdout.splitlines()
    for rel in untracked:
        p = root / rel
        name = p.name
        if name in JUNK_NAMES or name.endswith(JUNK_SUFFIXES):
            findings.append(f"{rel}: junk/secret-looking untracked file")
            continue
        try:
            if p.stat().st_size > MAX_UNTRACKED_BYTES:
                findings.append(f"{rel}: untracked file over 5MB")
                continue
            if p.suffix in DEBUG_PATTERNS or p.suffix in (".py", ".ts", ".tsx", ".js"):
                text = p.read_text(errors="replace")
                pseudo = "+++ b/" + rel + "\n" + "\n".join("+" + ln for ln in text.splitlines())
                findings.extend(scan_diff_text(pseudo))
        except OSError:
            continue
    if findings:
        return False, "\n".join(findings)
    return True, f"clean: {len(untracked)} untracked file(s) checked, diff scanned"


def modules_source(frontend: Path) -> Path:
    """The node_modules a frontend builds with: its own, or the live tree's
    when it is a worktree (a worktree is a checkout, not an install)."""
    own = frontend / "node_modules"
    return own if own.is_dir() else FRONTEND_ROOT / "node_modules"


@contextmanager
def shared_node_modules(frontend: Path, source: Optional[Path] = None):
    """For the duration of a frontend gate in a worktree, link the live
    node_modules in; afterwards remove only the link. os.rmdir on a junction
    and os.unlink on a symlink never follow it, so the shared modules are never
    touched (removing a worktree with a junction inside can delete the target's
    files)."""
    target = frontend / "node_modules"
    source = source or (FRONTEND_ROOT / "node_modules")
    if target.exists() or not source.is_dir():
        yield
        return
    if WINDOWS:
        import _winapi

        _winapi.CreateJunction(str(source), str(target))
    else:
        os.symlink(source, target, target_is_directory=True)
    try:
        yield
    finally:
        try:
            if WINDOWS:
                os.rmdir(target)
            else:
                os.unlink(target)
        except OSError:
            pass


def frontend_gate(frontend: Path, cmd: Sequence[str], timeout: float = 900.0) -> GateFn:
    """A frontend gate run in another tree (a worktree), with the shared modules linked in."""
    def run() -> Tuple[bool, str]:
        with shared_node_modules(frontend):
            proc = subprocess.run(list(cmd), cwd=str(frontend), capture_output=True, text=True, timeout=timeout)
        return proc.returncode == 0, (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return run


def isolated_next_build(frontend: Path = FRONTEND_ROOT, timeout: float = 1200.0) -> Tuple[bool, str]:
    """Run ``next build`` on a scratch copy (sources copied, node_modules
    hard-linked on Linux or junctioned on Windows) so a live ``next start``
    serving frontend/.next is never disturbed. Same compiler, same config;
    only the output directory differs."""
    import shutil
    import tempfile

    modules = modules_source(frontend)
    if not modules.is_dir():
        raise RuntimeError("frontend/node_modules missing; run npm install")
    scratch = Path(tempfile.mkdtemp(prefix="syrax-next-build-"))
    try:
        shutil.copytree(frontend, scratch, dirs_exist_ok=True, symlinks=True,
                        ignore=shutil.ignore_patterns("node_modules", ".next"))
        _link_tree(modules, scratch / "node_modules")
        cache = frontend / ".next" / "cache"
        if not cache.is_dir():
            cache = FRONTEND_ROOT / ".next" / "cache"
        if cache.is_dir():  # reuse the local build cache (Google Fonts are fetched at build time; the cache makes the gate offline-safe)
            (scratch / ".next").mkdir(exist_ok=True)
            _link_tree(cache, scratch / ".next" / "cache")
        proc = subprocess.run([_npx(), "next", "build"], cwd=str(scratch), capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return proc.returncode == 0, out
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _link_tree(src: Path, dst: Path) -> None:
    """Make ``dst`` share ``src``'s files without a full copy: ``cp -al`` on
    Linux, per-file hard links on Windows (Turbopack refuses a junction or
    symlink that points outside the project), a real copy when linking fails
    (different filesystem)."""
    import shutil

    if not WINDOWS:
        link = subprocess.run(["cp", "-al", str(src), str(dst)], capture_output=True, text=True, timeout=300)
        if link.returncode == 0:
            return

    def link_or_copy(a: str, b: str) -> None:
        try:
            os.link(a, b)
        except OSError:
            shutil.copy2(a, b)

    shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True, copy_function=link_or_copy)


def _npx() -> str:
    return shutil.which("npx") or "npx"


def _npm() -> str:
    return shutil.which("npm") or "npm"


def venv_python(backend: Path = BACKEND_ROOT) -> str:
    """The backend's own interpreter: ``.venv/bin/python`` on Linux,
    ``.venv/Scripts/python.exe`` on Windows, the running one as a fallback."""
    candidate = backend / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
    return str(candidate) if candidate.exists() else sys.executable


def performance_gate(journal_path: Optional[str] = None) -> Tuple[bool, str]:
    """Run the benchmark suite and compare with the last stored run. BASELINE and
    PASS are ok; REGRESSION fails. Without a journal there is nothing to compare
    with, so the run is recorded nowhere and reported as a baseline."""
    from syrax import bench

    path = journal_path or os.getenv("SYRAX_JOURNAL_FILE")
    if not path:
        metrics = bench.run_suite()
        status, deltas = bench.compare(metrics, None)
        return True, bench.format_report({"status": status, "deltas": deltas, "compared_to": None}) + "\n(no journal: not recorded)"
    j = Journal(path, recover=False)
    try:
        row = bench.run_and_record(j)
    finally:
        j.close()
    return row["status"] != "REGRESSION", bench.format_report(row)


def default_gates(root: Path = REPO_ROOT, journal_path: Optional[str] = None) -> List[Gate]:
    """The release gate for the tree at ``root``: the live repository, or a
    worktree where SYRAX prepared a change (M1, isolated evolution). The checks
    are the same; only the directories they run in follow ``root``."""
    root = Path(root)
    backend, frontend = root / "backend", root / "frontend"
    live = root.resolve() == REPO_ROOT.resolve()
    py = venv_python()
    test_env = {
        "OPENMANUS_DISABLE_BROWSER_USE": "1",
        "SYRAX_DISABLE_WHISPER_WARMUP": "1",
        "SYRAX_BROWSER": "0",
    }
    npx = _npx()
    tsc, eslint, node_test = [npx, "tsc", "--noEmit"], [npx, "eslint", "."], [_npm(), "test", "--silent"]

    def fe(name: str, cmd: List[str]) -> Gate:
        return Gate(name, cmd, cwd=FRONTEND_ROOT) if live else Gate(name, frontend_gate(frontend, cmd))

    return [
        Gate("py_compile", [py, "-m", "compileall", "-q", "syrax"], cwd=backend),
        # Live 2026-10-11: after the UI moved to port 3001 (SYRAX_ALLOWED_ORIGINS set for the user),
        # the running SYRAX's gate passed that to the tests, whose test server then refused their
        # localhost:3000 origin with 403: 62 failures, every release blocked. The tests run on
        # their own settings only.
        # a test that runs past faulthandler_timeout prints every thread's stack into the evidence
        # (live 2026-10-12: the suite hung twice past the gate's timeout and nothing said where)
        Gate("pytest", [py, "-m", "pytest", "syrax", "-q", "-p", "no:cacheprovider", "-o", "faulthandler_timeout=300"],
             cwd=backend, env=test_env,
             drop_env_prefixes=("SYRAX_",)),
        fe("tsc", tsc),
        fe("eslint", eslint),
        fe("node_test", node_test),
        # the desktop HUD's link to the core (hud/link.js) is pure and tested with node --test, no install needed
        Gate("hud_test", [_npm(), "test", "--silent"], cwd=root / "hud"),
        Gate("next_build", isolated_next_build if live else (lambda: isolated_next_build(frontend))),
        Gate("diff_scan", lambda: diff_scan(root)),
        Gate("performance", lambda: performance_gate(journal_path), required=False, timeout=600),
    ]


def format_report(v: Verification) -> str:
    lines = [f"VERIFICATION {v.status}  git_head={v.git_head or '?'}"]
    for g in v.gates:
        flag = "required" if g.required else "optional"
        code = "-" if g.exit_code is None else str(g.exit_code)
        lines.append(f"  {g.status:<13} {g.name:<12} exit={code:<3} {g.duration_ms:>7}ms  ({flag})")
        if g.status != "PASS":
            for ln in g.evidence.splitlines()[-8:]:
                lines.append(f"      | {ln}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run the SYRAX verification gate.")
    ap.add_argument("--gate", action="append", help="run only these gates (repeatable)")
    ap.add_argument("--json", action="store_true", help="print the verification as JSON")
    ap.add_argument("--journal", help="journal file to record into (default: SYRAX_JOURNAL_FILE or none)")
    args = ap.parse_args(argv)
    gates = default_gates(journal_path=args.journal or os.getenv("SYRAX_JOURNAL_FILE"))
    if args.gate:
        wanted = set(args.gate)
        gates = [g for g in gates if g.name in wanted]
        missing = wanted - {g.name for g in gates}
        if missing:
            sys.stderr.write(f"unknown gate(s): {', '.join(sorted(missing))}\n")
            return 2
    journal = None
    path = args.journal or os.getenv("SYRAX_JOURNAL_FILE")
    if path:
        journal = Journal(path, recover=False)
    v = run_gates(gates, journal=journal)
    if journal is not None:
        journal.close()
    sys.stdout.write((json.dumps(v.to_dict(), indent=2) if args.json else format_report(v)) + "\n")
    return 0 if v.status == "GREEN" else 1


if __name__ == "__main__":
    sys.exit(main())
