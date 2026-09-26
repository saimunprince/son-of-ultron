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
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from syrax.journal import BACKEND_ROOT, Journal, _git_head

REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = REPO_ROOT / "frontend"
TAIL_LINES = 40

GateFn = Callable[[], Tuple[bool, str]]


@dataclass
class Gate:
    name: str
    cmd: Union[Sequence[str], GateFn]
    cwd: Path = REPO_ROOT
    required: bool = True
    env: Optional[Dict[str, str]] = None
    timeout: float = 900.0


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


def run_gate(gate: Gate) -> GateResult:
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
    env = {**os.environ, **(gate.env or {})}
    try:
        proc = subprocess.run(
            cmd, cwd=str(gate.cwd), env=env, capture_output=True, text=True, timeout=gate.timeout
        )
    except FileNotFoundError as e:
        return GateResult(
            gate.name, gate.required, "NOT_VERIFIED", None,
            int((time.monotonic() - started) * 1000), f"cannot start: {e}", " ".join(cmd),
        )
    except subprocess.TimeoutExpired:
        return GateResult(
            gate.name, gate.required, "NOT_VERIFIED", None,
            int((time.monotonic() - started) * 1000), f"timeout after {gate.timeout}s", " ".join(cmd),
        )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return GateResult(
        gate.name, gate.required, "PASS" if proc.returncode == 0 else "FAIL", proc.returncode,
        int((time.monotonic() - started) * 1000), _tail(out), " ".join(cmd),
    )


def run_gates(
    gates: Sequence[Gate], journal: Optional[Journal] = None, task_id: Optional[str] = None
) -> Verification:
    results = [run_gate(g) for g in gates]
    green = all(r.status == "PASS" for r in results if r.required)
    v = Verification(
        status="GREEN" if green else "BLOCKED",
        ts=time.time(),
        git_head=_git_head(REPO_ROOT),
        gates=results,
    )
    if journal is not None:
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
        cwd=str(root), capture_output=True, text=True, timeout=60,
    )
    if diff.returncode != 0:
        raise RuntimeError(f"git diff failed: {diff.stderr.strip()}")
    findings = scan_diff_text(diff.stdout)
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=str(root), capture_output=True, text=True, timeout=60,
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


def isolated_next_build(frontend: Path = FRONTEND_ROOT, timeout: float = 1200.0) -> Tuple[bool, str]:
    """Run ``next build`` on a scratch copy (sources rsynced, node_modules
    hard-linked) so a live ``next start`` serving frontend/.next is never
    disturbed. Same compiler, same config; only the output directory differs."""
    import shutil
    import tempfile

    if not (frontend / "node_modules").is_dir():
        raise RuntimeError("frontend/node_modules missing; run npm install")
    scratch = Path(tempfile.mkdtemp(prefix="syrax-next-build-"))
    try:
        subprocess.run(
            ["rsync", "-a", "--exclude", "node_modules", "--exclude", ".next", f"{frontend}/", f"{scratch}/"],
            check=True, capture_output=True, text=True, timeout=120,
        )
        link = subprocess.run(["cp", "-al", str(frontend / "node_modules"), str(scratch / "node_modules")], capture_output=True, text=True, timeout=300)
        if link.returncode != 0:  # different filesystem: fall back to a real copy
            shutil.copytree(frontend / "node_modules", scratch / "node_modules", symlinks=True)
        cache = frontend / ".next" / "cache"
        if cache.is_dir():  # reuse the local build cache (Google Fonts are fetched at build time; the cache makes the gate offline-safe)
            (scratch / ".next").mkdir(exist_ok=True)
            subprocess.run(["cp", "-al", str(cache), str(scratch / ".next" / "cache")], capture_output=True, text=True, timeout=300)
        proc = subprocess.run(["npx", "next", "build"], cwd=str(scratch), capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return proc.returncode == 0, out
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def default_gates(root: Path = REPO_ROOT) -> List[Gate]:
    py = str(BACKEND_ROOT / ".venv" / "bin" / "python")
    test_env = {
        "OPENMANUS_DISABLE_BROWSER_USE": "1",
        "SYRAX_DISABLE_WHISPER_WARMUP": "1",
        "SYRAX_BROWSER": "0",
    }
    npx = "npx"
    return [
        Gate("py_compile", [py, "-m", "compileall", "-q", "syrax"], cwd=BACKEND_ROOT),
        Gate("pytest", [py, "-m", "pytest", "syrax", "-q", "-p", "no:cacheprovider"], cwd=BACKEND_ROOT, env=test_env),
        Gate("tsc", [npx, "tsc", "--noEmit"], cwd=FRONTEND_ROOT),
        Gate("eslint", [npx, "eslint", "."], cwd=FRONTEND_ROOT),
        Gate("node_test", ["npm", "test", "--silent"], cwd=FRONTEND_ROOT),
        Gate("next_build", isolated_next_build),
        Gate("diff_scan", lambda: diff_scan(root)),
        Gate("performance", lambda: (_ for _ in ()).throw(RuntimeError("no benchmark defined yet")), required=False),
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
    gates = default_gates()
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
