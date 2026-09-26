"""Experiments over code versions: is commit B better than commit A, measured?

For each ref a detached git worktree is created, the backend test suite is run
in it (with this venv's Python), and the benchmark suite is run from that
version's code. The comparison is stored as an experiment whose arms are the
two commits and whose verdict comes from the numbers: tests first (a version
with more failures loses), then benchmark regressions (>50 % and >5 ms).

    compare_versions {base, candidate}   e.g. base "HEAD~1", candidate "HEAD"

Cost: about two test-suite runs (a few minutes). Worktrees are removed afterwards.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from pydantic import Field

from app.tool.base import BaseTool, ToolResult

from syrax.bench import compare as bench_compare
from syrax.journal import BACKEND_ROOT, Journal, JournalError

REPO_ROOT = BACKEND_ROOT.parent
TEST_TIMEOUT_S = 900.0


def _git(args, cwd: Path, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def parse_pytest(out: str) -> Dict[str, int]:
    passed = failed = errors = 0
    m = re.search(r"(\d+) passed", out)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", out)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+) error", out)
    if m:
        errors = int(m.group(1))
    return {"passed": passed, "failed": failed + errors}


# Files the code needs at runtime that are not in git (config.toml is required by app.config
# to import at all). They are copied from the live checkout into the temporary worktree.
UNTRACKED_RUNTIME_FILES = ("backend/config/config.toml", "backend/config/mcp.json")


def prepare_worktree(worktree: Path, source_root: Path = REPO_ROOT) -> list:
    """Copy untracked runtime files a version needs to import and run. Returns what was copied."""
    copied = []
    for rel in UNTRACKED_RUNTIME_FILES:
        src, dst = source_root / rel, worktree / rel
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            copied.append(rel)
    return copied


def measure_worktree(worktree: Path, timeout: float = TEST_TIMEOUT_S) -> dict:
    """Run tests + benchmark for the code in ``worktree``. Never raises; records what it could measure."""
    backend = worktree / "backend"
    copied = prepare_worktree(worktree)
    env = {**os.environ, "OPENMANUS_DISABLE_BROWSER_USE": "1", "SYRAX_DISABLE_WHISPER_WARMUP": "1", "SYRAX_BROWSER": "0",
           "PYTHONPATH": str(backend), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("SYRAX_JOURNAL_FILE", None)
    out: Dict[str, Any] = {"tests": None, "bench": None, "notes": [], "copied": copied}
    if not (backend / "syrax").is_dir():
        out["notes"].append("no backend/syrax in this version")
        return out
    try:
        proc = subprocess.run([sys.executable, "-m", "pytest", "syrax", "-q", "-p", "no:cacheprovider"], cwd=str(backend), env=env,
                              capture_output=True, text=True, timeout=timeout)
        out["tests"] = {**parse_pytest(proc.stdout + proc.stderr), "exit_code": proc.returncode}
        tail = (proc.stdout + proc.stderr).strip().splitlines()
        if out["tests"]["passed"] == 0:
            out["notes"].append("no test passed: " + (tail[-1][:160] if tail else "no output"))
    except subprocess.TimeoutExpired:
        out["notes"].append(f"tests timed out after {timeout}s")
    if (backend / "syrax" / "bench.py").is_file():
        try:
            proc = subprocess.run([sys.executable, "-m", "syrax.bench", "--json"], cwd=str(backend), env=env, capture_output=True, text=True, timeout=600)
            if proc.returncode in (0, 1):
                data = json.loads(proc.stdout)
                out["bench"] = data.get("metrics")
            else:
                out["notes"].append(f"bench failed: {proc.stderr.strip()[-200:]}")
        except subprocess.TimeoutExpired:
            out["notes"].append("bench timed out")
        except ValueError:
            out["notes"].append("bench produced no JSON: " + proc.stderr.strip()[-160:])
    else:
        out["notes"].append("no benchmark suite in this version")
    return out


def judge_versions(base: dict, cand: dict) -> tuple[str, str]:
    bt, ct = base.get("tests"), cand.get("tests")
    if bt is None or ct is None:
        return "INCONCLUSIVE", "tests could not be measured on both versions"
    if ct["failed"] > bt["failed"]:
        return "BASELINE_BETTER", f"candidate has more failing tests ({ct['failed']} vs {bt['failed']})"
    if ct["failed"] < bt["failed"]:
        return "CANDIDATE_BETTER", f"candidate has fewer failing tests ({ct['failed']} vs {bt['failed']})"
    if base.get("bench") and cand.get("bench"):
        status, deltas = bench_compare(cand["bench"], base["bench"])
        regressed = [k for k, d in deltas.items() if d["regression"]]
        if regressed:
            return "BASELINE_BETTER", f"same test results ({ct['passed']} passed); candidate regressed {', '.join(regressed)}"
        faster = [k for k, d in deltas.items() if d["pct"] is not None and d["pct"] < -50 and (d["before"] - d["now"]) > 5]
        if faster:
            return "CANDIDATE_BETTER", f"same test results; candidate is >50% faster on {', '.join(faster)}"
        return "NO_DIFFERENCE", f"same test results ({ct['passed']} passed, {ct['failed']} failed); no benchmark regression"
    return "NO_DIFFERENCE", f"same test results ({ct['passed']} passed, {ct['failed']} failed); benchmark not comparable"


class VersionComparer:
    def __init__(self, journal: Journal, root: Path = REPO_ROOT, measurer: Optional[Callable[[Path], dict]] = None,
                 task_id_provider: Optional[Callable[[], Optional[str]]] = None):
        self.journal = journal
        self.root = Path(root)
        self.measure = measurer or measure_worktree
        self.task_id_provider = task_id_provider or (lambda: None)

    def _resolve(self, ref: str) -> str:
        out = _git(["rev-parse", "--verify", f"{ref}^{{commit}}"], self.root)
        if out.returncode != 0:
            raise ValueError(f"unknown ref {ref!r}: {out.stderr.strip()[:120]}")
        return out.stdout.strip()

    def _measure_ref(self, ref: str, sha: str) -> dict:
        tmp = Path(tempfile.mkdtemp(prefix="syrax-version-"))
        wt = tmp / "wt"
        try:
            add = _git(["worktree", "add", "--detach", str(wt), sha], self.root)
            if add.returncode != 0:
                raise RuntimeError(f"git worktree failed for {ref}: {add.stderr.strip()[:200]}")
            started = time.monotonic()
            result = self.measure(wt)
            result["ms"] = int((time.monotonic() - started) * 1000)
            return {"ref": ref, "sha": sha, **result}
        finally:
            _git(["worktree", "remove", "--force", str(wt)], self.root)
            _git(["worktree", "prune"], self.root)
            shutil.rmtree(tmp, ignore_errors=True)

    async def compare(self, base: str, candidate: str, hypothesis: Optional[str] = None) -> dict:
        base_sha, cand_sha = self._resolve(base), self._resolve(candidate)
        if base_sha == cand_sha:
            raise ValueError("base and candidate are the same commit")
        task_id = self.task_id_provider()
        hyp = hypothesis or f"{candidate} is at least as good as {base}"
        await self.journal.record("experiment.started", {"hypothesis": hyp[:160], "metric": "tests+bench", "repeats": 1, "versions": [base_sha[:10], cand_sha[:10]]}, task_id=task_id)
        b = await asyncio.to_thread(self._measure_ref, base, base_sha)
        c = await asyncio.to_thread(self._measure_ref, candidate, cand_sha)
        verdict, conclusion = judge_versions(b, c)
        row = await self.journal.run(
            self.journal.add_experiment_sync, hyp, b, c, "tests+bench",
            {"baseline": b.get("tests"), "candidate": c.get("tests"), "bench_base": b.get("bench"), "bench_candidate": c.get("bench")},
            conclusion, verdict, None,
            {"CANDIDATE_BETTER": "keep the candidate", "BASELINE_BETTER": "do not ship the candidate; investigate", "NO_DIFFERENCE": "no measured difference", "INCONCLUSIVE": "make both versions measurable first"}[verdict],
            task_id,
        )
        return row


def render(row: dict) -> str:
    b, c = row["baseline"], row["candidate"]

    def arm(a):
        t = a.get("tests") or {}
        return f"{a.get('ref')} ({str(a.get('sha'))[:10]}): tests {t.get('passed', '?')} passed / {t.get('failed', '?')} failed" + (f"; notes: {'; '.join(a['notes'])}" if a.get("notes") else "")

    return "\n".join([
        f"VERSION EXPERIMENT #{row['id']} {row['verdict']}",
        f"hypothesis: {row['hypothesis']}",
        "baseline  " + arm(b),
        "candidate " + arm(c),
        f"conclusion: {row['conclusion']}",
        f"next: {row['next_action']}",
    ])


class CompareVersionsTool(BaseTool):
    name: str = "compare_versions"
    description: str = (
        "Measure two commits of SYRAX's own repository against each other: the backend test suite and the "
        "benchmark suite run in a clean worktree of each. The verdict comes from the numbers (tests first, "
        "then benchmark regressions). Use after a release to check the change did not make SYRAX worse, "
        "e.g. base 'HEAD~1', candidate 'HEAD'. Takes a few minutes."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "base": {"type": "string", "description": "git ref of the baseline, e.g. HEAD~1"},
            "candidate": {"type": "string", "description": "git ref of the candidate, e.g. HEAD"},
            "hypothesis": {"type": "string"},
        },
        "required": ["base", "candidate"],
    }
    comparer: Optional[Any] = Field(default=None, exclude=True)

    async def execute(self, base: str, candidate: str, hypothesis: Optional[str] = None) -> ToolResult:
        if self.comparer is None:
            return ToolResult(error="version comparer unavailable")
        try:
            row = await self.comparer.compare(base, candidate, hypothesis)
        except (ValueError, RuntimeError, JournalError) as e:
            return ToolResult(error=f"compare_versions refused: {e}")
        return ToolResult(output=render(row))
