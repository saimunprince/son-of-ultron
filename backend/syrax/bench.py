"""SYRAX benchmark suite: measure SYRAX's own mechanisms, compare with the last
run, and say REGRESSION / PASS / BASELINE from numbers, never from feelings.

Metrics (all on a throwaway journal so the real one is untouched):
  journal_record_p50_ms / _p95_ms   one durable event write (BEGIN…COMMIT + fsync)
  checkpoint_p95_ms                 checkpoint with a 40-message context
  tool_stats_ms                     the capability-registry query over 600 events
  recovery_ms                       recover_interrupted over 20 dead tasks
  selfmodel_summary_ms              SelfModel.snapshot("summary")
  events_between_ms                 a replay window query

A regression is a metric that got slower than the previous run by more than
REGRESSION_PCT and by more than MIN_ABS_MS (small absolute jitter is not a
regression). The first run is a BASELINE, not a PASS.

    .venv/bin/python -m syrax.bench [--json] [--journal path]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from syrax.journal import Journal, _git_head

REGRESSION_PCT = 50.0
MIN_ABS_MS = 5.0
LOWER_IS_BETTER = True


def _timeit(fn: Callable[[], None], n: int) -> List[float]:
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000)
    return out


def _p(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    k = min(len(vals) - 1, max(0, int(round(q * (len(vals) - 1)))))
    return round(vals[k], 3)


def run_suite(workdir: Optional[Path] = None) -> Dict[str, float]:
    """Run every benchmark on a scratch journal; returns {metric: ms}.
    A scratch directory created here is removed afterwards (the suite must not
    leave 700 KB behind on every release)."""
    own_tmp = workdir is None
    tmp = Path(workdir or tempfile.mkdtemp(prefix="syrax-bench-"))
    j = Journal(tmp / "bench.db", recover=False)
    try:
        t = j.start_task_sync("bench")
        rec = _timeit(lambda: j.record_sync("think", {"step": 1, "content": "x" * 200}, task_id=t), 200)
        ctx = [{"role": "user", "content": "y" * 500}] * 40
        cps = _timeit(lambda: j.checkpoint_sync(t, "bench", context=ctx), 20)
        for i in range(200):
            j.record_sync("tool.started", {"id": f"c{i}", "name": f"tool{i % 5}", "args": {}}, task_id=t)
            j.record_sync("tool.completed" if i % 3 else "tool.failed", {"id": f"c{i}", "name": f"tool{i % 5}", "ok": bool(i % 3), "output": "o"}, task_id=t)
        stats_ms = _timeit(lambda: j.tool_stats(), 5)
        between_ms = _timeit(lambda: j.events_between(0), 5)
        dead = Journal(tmp / "bench.db", boot_id="dead", recover=False)
        for i in range(20):
            d = dead.start_task_sync(f"dead {i}")
            dead.record_sync("tool.started", {"id": "x", "name": "python_execute", "args": {"code": "1"}}, task_id=d)
        dead.close()
        t0 = time.perf_counter()
        j2 = Journal(tmp / "bench.db")  # recovery runs in the constructor
        recovery_ms = (time.perf_counter() - t0) * 1000
        j2.close()
        from syrax.selfmodel import SelfModel

        sm = SelfModel(j)
        sm.tools_provider = lambda: [f"tool{i}" for i in range(5)]
        sm_ms = _timeit(lambda: sm.snapshot("summary"), 3)
        return {
            "journal_record_p50_ms": _p(rec, 0.5),
            "journal_record_p95_ms": _p(rec, 0.95),
            "checkpoint_p95_ms": _p(cps, 0.95),
            "tool_stats_ms": round(statistics.median(stats_ms), 3),
            "events_between_ms": round(statistics.median(between_ms), 3),
            "recovery_ms": round(recovery_ms, 3),
            "selfmodel_summary_ms": round(statistics.median(sm_ms), 3),
        }
    finally:
        j.close()
        if own_tmp:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


def compare(current: Dict[str, float], previous: Optional[Dict[str, float]]) -> Tuple[str, Dict[str, dict]]:
    """Returns (status, deltas). status: BASELINE (nothing to compare), PASS or REGRESSION."""
    if not previous:
        return "BASELINE", {k: {"now": v, "before": None, "pct": None, "regression": False} for k, v in current.items()}
    deltas: Dict[str, dict] = {}
    regressed = False
    for k, v in current.items():
        before = previous.get(k)
        if before is None:
            deltas[k] = {"now": v, "before": None, "pct": None, "regression": False}
            continue
        pct = ((v - before) / before * 100) if before else 0.0
        reg = pct > REGRESSION_PCT and (v - before) > MIN_ABS_MS
        regressed |= reg
        deltas[k] = {"now": v, "before": before, "pct": round(pct, 1), "regression": reg}
    return ("REGRESSION" if regressed else "PASS"), deltas


def run_and_record(journal: Journal, task_id: Optional[str] = None) -> dict:
    """Measure, compare with the last stored run, store the result."""
    metrics = run_suite()
    prev = journal.benchmarks(limit=1)
    status, deltas = compare(metrics, prev[0]["metrics"] if prev else None)
    return journal.add_benchmark_sync(metrics, status, deltas, compared_to=prev[0]["id"] if prev else None, task_id=task_id)


def format_report(row: dict) -> str:
    lines = [f"BENCHMARK {row['status']}" + (f" (vs #{row['compared_to']})" if row.get("compared_to") else "")]
    for k, d in row["deltas"].items():
        before = "" if d["before"] is None else f"  before {d['before']}ms ({d['pct']:+.1f}%)"
        lines.append(f"  {'REGRESSION' if d['regression'] else 'ok':<10} {k:<24} {d['now']:>9}ms{before}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the SYRAX benchmark suite.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--journal", help="journal to compare against and record into (default SYRAX_JOURNAL_FILE or none)")
    args = ap.parse_args(argv)
    path = args.journal or os.getenv("SYRAX_JOURNAL_FILE")
    if path:
        j = Journal(path, recover=False)
        row = run_and_record(j)
        j.close()
    else:
        metrics = run_suite()
        status, deltas = compare(metrics, None)
        row = {"status": status, "metrics": metrics, "deltas": deltas, "compared_to": None, "git_head": _git_head(Path.cwd())}
    sys.stdout.write((json.dumps(row, indent=2, default=str) if args.json else format_report(row)) + "\n")
    return 1 if row["status"] == "REGRESSION" else 0


if __name__ == "__main__":
    sys.exit(main())
