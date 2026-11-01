"""Revert a release of SYRAX's own that made task quality fall (audit 2026-11-01, self-improvement F12).

Before, a regression became an objective naming the suspect commits and asking the brain to compare and maybe revert;
nothing reverted on its own, so a bad own release stayed in main until a human looked. Now, when the latest full
quality run is a REGRESSION of at least REVERT_MIN_DROP points and exactly one of SYRAX's own code commits landed
between it and the run before, that commit's `git revert` is made in an isolated worktree and released like any change:
the full gate and a second brain's review decide, and a held or failed revert changes nothing. Once per commit.
A human's commit is never reverted here; nor is a docs-only one."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from syrax.journal import BACKEND_ROOT, Journal

REVERT_MIN_DROP = 5.0  # percentage points of the full suite
FULL_CASES = 10  # a subset re-run is not the suite (rise.FULL_QUALITY_CASES)
PLAN = {"why": "the latest full quality run regressed after this commit, the only own code change between the runs",
        "risk": "the reverted change's own fix is undone; its objective may open again",
        "tests": "the full gate; the next quality run measures the result"}


def candidate(journal: Journal) -> Optional[Dict[str, Any]]:
    """The own code commit to revert, or None."""
    runs = journal.quality_runs(limit=2)
    if len(runs) < 2:
        return None
    now, before = runs[0], runs[1]
    if now.get("status") != "REGRESSION" or len(now.get("results") or []) < FULL_CASES:
        return None
    if (now.get("delta") or 0) > -REVERT_MIN_DROP:
        return None
    own = []
    for e in journal.events_between(before["ts"], now["ts"], limit=10000):
        if e["type"] != "commit.created" or not e["payload"].get("commit"):
            continue
        files = [str(f) for f in (e["payload"].get("files") or [])]
        if any(not f.startswith("docs/") for f in files):
            own.append({"commit": str(e["payload"]["commit"]), "files": files, "summary": str(e["payload"].get("summary") or ""),
                        "task_id": e.get("task_id")})
    if len(own) != 1:
        return None  # none to blame, or several: compare_versions decides which (the regression objective)
    c = own[0]
    if journal.get_meta(f"release_revert:{c['commit'][:12]}"):
        return None
    return {**c, "run_id": now.get("id"), "delta": now.get("delta"), "pass_rate": now.get("pass_rate")}


async def revert(journal: Journal, root: Path = BACKEND_ROOT.parent, gates: Optional[Callable] = None,
                 reviewer: Optional[Callable] = None) -> Dict[str, Any]:
    """Revert the candidate through the release path. Returns the release report, or {"outcome": "SKIPPED"}."""
    from syrax.devloop import DevLoop, _git

    c = candidate(journal)
    if c is None:
        return {"outcome": "SKIPPED"}
    root = Path(root)
    short = c["commit"][:12]
    journal.set_meta(f"release_revert:{short}", str(time.time()))
    t = journal.start_task_sync(f"[MAINTENANCE] revert own release {short}: quality fell {c['delta']:+.1f} pp", kind="autonomous")
    dl = DevLoop(journal, root=root, gates=gates, task_id_provider=lambda: t, worktrees_dir=root / ".syrax" / "maintenance")
    dl.reviewer = reviewer
    report: Dict[str, Any]
    try:
        await asyncio.to_thread(dl.begin_task)
        wt = await asyncio.to_thread(dl.isolate, t)
        r = await asyncio.to_thread(_git, ["revert", "--no-commit", c["commit"]], wt)
        if r.returncode != 0:
            report = {"outcome": "FAILED", "error": f"git revert did not apply: {(r.stderr or r.stdout).strip()[:300]}"}
        else:
            summary = (f"revert {short} ({c['summary'][:80]}): quality run #{c['run_id']} fell {c['delta']:+.1f} pp "
                       f"to {c['pass_rate']}%, and it was the only own code change since the run before")
            report = await dl.release(summary, dict(PLAN))
    except Exception as e:
        report = {"outcome": "FAILED", "error": f"{type(e).__name__}: {e}"[:400]}
    finally:
        await asyncio.to_thread(dl.discard)
    await journal.record("release.reverted", {"commit": c["commit"], "run_id": c["run_id"], "delta": c["delta"],
                                              "outcome": report.get("outcome"), "revert_commit": report.get("commit"),
                                              "error": report.get("error")}, task_id=t)
    if report.get("outcome") == "COMMITTED":
        text = f"Reverted {short}: {report.get('commit', '')[:12]}"
        await journal.record("final", {"text": text}, task_id=t)
        await journal.record("task.completed", {"status": "SUCCESS", "result": text}, task_id=t)
    else:
        await journal.record("task.failed", {"error": f"revert of {short} not landed: {report.get('outcome')} {report.get('error') or ''}"[:300]},
                             task_id=t)
    return report
