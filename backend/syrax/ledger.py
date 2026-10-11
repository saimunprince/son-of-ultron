"""Publishing the rise ledger: once a day SYRAX regenerates docs/RISE.md from
its own journal and lands it the way every self-change lands: an isolated
worktree, the full gate, a second brain's review, a fast-forward of the
running tree. No model writes a word of it; syrax.rise computes every number.

Runs from the autonomy cycle when it has nothing else to do and the service
asks for it (SYRAX_PUBLISH_RISE=1, set by the launcher). A failed attempt is
retried no sooner than RETRY_S later, so a blocked gate does not run every cycle.

This file decides what SYRAX publishes about itself, so its own releases may
not change it (devloop.JUDGES).
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from syrax.journal import BACKEND_ROOT, Journal

REPO_ROOT = BACKEND_ROOT.parent
EVERY_S = 86400.0
RETRY_S = 6 * 3600.0
PUBLISHED, ATTEMPTED = "rise_published", "rise_attempted"
SUMMARY = "docs(rise): the ledger, regenerated from the journal"
PLAN = {"why": "the rise ledger is published daily from the journal (M3, evidence without gaps)",
        "risk": "docs only; every number is computed by syrax.rise, a judge file",
        "tests": "the full gate runs on the worktree"}


def _since(journal: Journal, key: str, now: float) -> float:
    try:
        return now - float(journal.get_meta(key) or 0)
    except ValueError:
        return now


def due(journal: Journal, now: Optional[float] = None) -> bool:
    now = now or time.time()
    return _since(journal, PUBLISHED, now) >= EVERY_S and _since(journal, ATTEMPTED, now) >= RETRY_S


async def publish(journal: Journal, root: Path = REPO_ROOT, gates: Optional[Callable] = None,
                  reviewer: Optional[Callable] = None, now: Optional[float] = None, force: bool = False) -> Dict[str, Any]:
    """Regenerate docs/RISE.md in an isolated worktree and release it. Returns the release report
    (outcome COMMITTED, ROLLED_BACK, REVIEW_REJECTED, COMMIT_FAILED, REFUSED or FAILED)."""
    from syrax import rise
    from syrax.devloop import DevLoop

    now = now or time.time()
    if not force and not due(journal, now):
        return {"outcome": "SKIPPED", "reason": "published or attempted recently"}
    root = Path(root)
    journal.set_meta(ATTEMPTED, str(now))
    t = journal.start_task_sync("[MAINTENANCE] publish the rise ledger (docs/RISE.md) from the journal", kind="autonomous")
    # its own worktree folder: an objective's task prunes .syrax/worktrees, never this one
    dl = DevLoop(journal, root=root, gates=gates, task_id_provider=lambda: t, worktrees_dir=root / ".syrax" / "maintenance")
    dl.reviewer = reviewer
    report: Dict[str, Any]
    try:
        await asyncio.to_thread(dl.begin_task)
        wt = await asyncio.to_thread(dl.isolate, t)
        await journal.record("isolation.started", {"worktree": str(wt)}, task_id=t)
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(root), capture_output=True, text=True).stdout.strip() or "?"
        data = await asyncio.to_thread(rise.measure, journal.path, now)
        (wt / "docs").mkdir(parents=True, exist_ok=True)
        (wt / "docs" / "RISE.md").write_text(rise.render(data, head), encoding="utf-8", newline="\n")
        report = await dl.release(SUMMARY, dict(PLAN))
    except Exception as e:
        report = {"outcome": "FAILED", "error": str(e)[:300]}
    finally:
        await asyncio.to_thread(dl.discard)
    outcome = str(report.get("outcome"))
    if outcome == "COMMITTED":
        journal.set_meta(PUBLISHED, str(now))
        await journal.record("final", {"text": f"RISE ledger published: {str(report.get('commit') or '')[:12]}"}, task_id=t)
        await journal.record("task.completed", {"status": "SUCCESS", "result": f"RISE ledger published: {str(report.get('commit') or '')[:12]}"}, task_id=t)
    else:
        why = str(report.get("error") or report.get("verification") or outcome)[:300]
        await journal.record("task.failed", {"error": f"RISE ledger not published ({outcome}): {why}"}, task_id=t)
    report["task_id"] = t
    return report
