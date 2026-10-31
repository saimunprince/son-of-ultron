"""Publishing the rise ledger: once a day SYRAX regenerates docs/RISE.md from
its own journal and lands it the way every self-change lands: an isolated
worktree, the full gate, a second brain's review, a fast-forward of the
running tree. No model writes a word of it; syrax.rise computes every number.

With matrix=True (the cycle asks for it) docs/CAPABILITY_MATRIX.md is
regenerated in the same release: the test suite runs once on the worktree for
a JUnit report, syrax.probe checks the running service, and the journal's
last verification stands for the gate. syrax.capmatrix computes every status.

Runs from the autonomy cycle when it has nothing else to do and the service
asks for it (SYRAX_PUBLISH_RISE=1, set by the launcher). A failed attempt is
retried no sooner than RETRY_S later, so a blocked gate does not run every cycle.

This file decides what SYRAX publishes about itself, so its own releases may
not change it (devloop.JUDGES).
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from syrax.journal import BACKEND_ROOT, Journal

REPO_ROOT = BACKEND_ROOT.parent
EVERY_S = 86400.0
RETRY_S = 6 * 3600.0
PUBLISHED, ATTEMPTED = "rise_published", "rise_attempted"
SUMMARY = "docs(rise): the ledger and the devlog, regenerated from the journal"
SUMMARY_WITH_MATRIX = "docs(rise): the ledger, the devlog and the capability matrix, regenerated from evidence"
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


def run_junit(wt: Path, xml: Path) -> bool:
    """The release gate's own pytest command on the worktree, with a JUnit report."""
    import dataclasses

    from syrax import verify

    gate = next(g for g in verify.default_gates(wt) if g.name == "pytest")
    # Live 2026-10-28..31 (Linux): the confined gate may write only the worktree and its TMPDIR, and the report was
    # asked for beside the worktree, so it was never written and the capability matrix went stale. It is written in
    # the gate's TMPDIR and moved to `xml` afterwards.
    tmp_dir = Path((gate.env or {}).get("TMPDIR") or xml.parent)
    report = tmp_dir / f"{xml.name}"
    report.unlink(missing_ok=True)
    gate = dataclasses.replace(gate, name="pytest_junit", cmd=[*gate.cmd, f"--junitxml={report}"])
    verify.run_gate(gate)
    if report.exists() and report != xml:
        xml.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(report), str(xml))
    return xml.exists()


async def write_matrix(journal: Journal, wt: Path, xml: Path, head: str, junit: Optional[Callable] = None,
                       prober: Optional[Callable] = None) -> Optional[Dict[str, int]]:
    """Regenerate docs/CAPABILITY_MATRIX.md in the worktree. None when the test
    suite gave no report: a matrix without tests would call everything unverified."""
    from syrax import capmatrix, probe

    try:
        if not await asyncio.to_thread(junit or run_junit, wt, xml):
            return None
        evidence = await asyncio.to_thread(prober or probe.collect)
        last = journal.verifications(limit=1)
        rows, text = await asyncio.to_thread(
            capmatrix.build, Path(journal.path), xml, None, None, head, wt, None, evidence,
            capmatrix.gate_from_verification(last[0] if last else None), Path(journal.path).name)
        (wt / "docs" / "CAPABILITY_MATRIX.md").write_text(text, encoding="utf-8", newline="\n")
        return {s: sum(1 for r in rows if r["status"] == s) for s in capmatrix.ORDER}
    finally:
        xml.unlink(missing_ok=True)


async def publish(journal: Journal, root: Path = REPO_ROOT, gates: Optional[Callable] = None,
                  reviewer: Optional[Callable] = None, now: Optional[float] = None, force: bool = False,
                  matrix: bool = False, junit: Optional[Callable] = None, prober: Optional[Callable] = None) -> Dict[str, Any]:
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
        from syrax import devlog  # M6: one entry per day SYRAX ran, from the journal and git

        days = await asyncio.to_thread(devlog.entries, journal, now, root)
        (wt / "docs" / "DEVLOG.md").write_text(devlog.render(days, head), encoding="utf-8", newline="\n")
        from syrax import archive  # Phase 5: the archive of SYRAX's own variants

        (wt / "docs" / "ARCHIVE.md").write_text(await asyncio.to_thread(archive.render, journal, head), encoding="utf-8", newline="\n")
        counts = None
        if matrix:
            xml = root / ".syrax" / "maintenance" / f"{wt.name}-pytest.xml"  # beside the worktree, never committed
            counts = await write_matrix(journal, wt, xml, head, junit, prober)
        report = await dl.release(SUMMARY_WITH_MATRIX if counts else SUMMARY, dict(PLAN))
        report["matrix"] = counts
    except Exception as e:
        # 2026-10-19: "unsupported operand type(s) for +: 'NoneType' and 'str'" alone did not say where; the
        # journal keeps the exception's type and the line it came from.
        import traceback

        last = traceback.extract_tb(e.__traceback__)[-1:] or [None]
        where = f" at {Path(last[0].filename).name}:{last[0].lineno}" if last[0] else ""
        report = {"outcome": "FAILED", "error": f"{type(e).__name__}: {e}{where}"[:400]}
    finally:
        await asyncio.to_thread(dl.discard)
    outcome = str(report.get("outcome"))
    if outcome == "COMMITTED":
        journal.set_meta(PUBLISHED, str(now))
        text = f"RISE ledger published: {str(report.get('commit') or '')[:12]}"
        if report.get("matrix"):
            text += " · capability matrix " + " ".join(f"{s} {n}" for s, n in report["matrix"].items() if n)
        await journal.record("final", {"text": text}, task_id=t)
        await journal.record("task.completed", {"status": "SUCCESS", "result": text}, task_id=t)
    else:
        why = str(report.get("error") or report.get("verification") or outcome)[:300]
        await journal.record("task.failed", {"error": f"RISE ledger not published ({outcome}): {why}"}, task_id=t)
    report["task_id"] = t
    return report
