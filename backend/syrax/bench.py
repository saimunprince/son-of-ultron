"""SYRAX benchmark suite: measure SYRAX's own mechanisms, compare with the pinned
baseline and the last run, and say REGRESSION / PASS / BASELINE from numbers, never from feelings.

Metrics (all on a throwaway journal so the real one is untouched):
  journal_record_p50_ms / _p95_ms   one durable event write (BEGIN…COMMIT + fsync)
  checkpoint_p95_ms                 checkpoint with a 40-message context
  tool_stats_ms                     the capability-registry query over 600 events
  recovery_ms                       recover_interrupted over 20 dead tasks
  selfmodel_summary_ms              SelfModel.snapshot("summary")
  events_between_ms                 a replay window query

A regression is a metric that got slower by more than REGRESSION_PCT and by
more than MIN_ABS_MS (small absolute jitter is not a regression), measured
against two references: the PINNED baseline (meta key ``bench_baseline_id``)
and the previous run. The pinned baseline catches slow creep that no single
step trips; the previous run catches a sudden jump. The first recorded run is
a BASELINE, not a PASS, and becomes the pinned baseline when none is set. Only
a human re-pins it (``--pin-baseline``; no agent tool does).

    .venv/bin/python -m syrax.bench [--json] [--journal path] [--pin-baseline ID|latest]
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
BASELINE_KEY = "bench_baseline_id"  # journal meta: the pinned known-good run


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


def pinned_baseline(journal: Journal) -> Optional[dict]:
    """The pinned baseline row, or None when nothing is pinned (or the pinned
    row is gone)."""
    raw = journal.get_meta(BASELINE_KEY)
    try:
        return journal.benchmark(int(raw)) if raw else None
    except (TypeError, ValueError):
        return None


def pin_baseline(journal: Journal, benchmark_id: Optional[int] = None) -> dict:
    """Pin a recorded run as the baseline every later run is compared with
    (default: the latest). A human decision: run it from the CLI, never from
    an agent tool. Returns the pinned row."""
    if getattr(journal, "read_only", False):
        raise RuntimeError(f"journal {journal.path} is owned by a running SYRAX: stop it before re-pinning")
    row = journal.benchmark(int(benchmark_id)) if benchmark_id is not None else next(iter(journal.benchmarks(limit=1)), None)
    if row is None:
        raise ValueError(f"no benchmark #{benchmark_id}" if benchmark_id is not None else "no benchmark recorded yet")
    journal.set_meta(BASELINE_KEY, str(row["id"]))
    return row


def _oldest(journal: Journal) -> Optional[dict]:
    with journal._lock:
        r = journal._db.execute("SELECT id FROM benchmarks ORDER BY id ASC LIMIT 1").fetchone()
    return journal.benchmark(int(r[0])) if r else None


def evaluate(metrics: Dict[str, float], journal: Journal) -> Tuple[str, Dict[str, dict], Optional[dict], Optional[dict]]:
    """Compare ``metrics`` with the pinned baseline and with the previous run.
    Returns (status, deltas, baseline_row, previous_row). ``before``/``pct`` in
    each delta are against the baseline; ``prev``/``prev_pct`` against the
    previous run; ``regression`` is true when either comparison regressed."""
    previous = next(iter(journal.benchmarks(limit=1)), None)
    baseline = pinned_baseline(journal) or _oldest(journal)
    if baseline is None:
        status, deltas = compare(metrics, None)
        return status, deltas, None, None
    status, deltas = compare(metrics, baseline["metrics"])
    if previous is not None and previous["id"] != baseline["id"]:
        pstatus, pdeltas = compare(metrics, previous["metrics"])
        for k, d in deltas.items():
            p = pdeltas.get(k) or {}
            d["prev"], d["prev_pct"] = p.get("before"), p.get("pct")
            d["regression"] = bool(d["regression"] or p.get("regression"))
        if pstatus == "REGRESSION":
            status = "REGRESSION"
    return status, deltas, baseline, previous


def run_and_record(journal: Journal, task_id: Optional[str] = None) -> dict:
    """Measure, compare with the pinned baseline and the previous run, store the
    result. The first recorded run is pinned as the baseline when none is set."""
    metrics = run_suite()
    status, deltas, baseline, previous = evaluate(metrics, journal)
    row = journal.add_benchmark_sync(metrics, status, deltas, compared_to=baseline["id"] if baseline else None, task_id=task_id)
    if pinned_baseline(journal) is None:
        journal.set_meta(BASELINE_KEY, str((baseline or row)["id"]))
    row["baseline_id"] = int(journal.get_meta(BASELINE_KEY))
    row["previous_id"] = previous["id"] if previous else None
    return row


def format_report(row: dict) -> str:
    head = f"BENCHMARK {row['status']}"
    if row.get("compared_to"):
        head += f" (vs pinned baseline #{row['compared_to']}"
        if row.get("previous_id") and row["previous_id"] != row["compared_to"]:
            head += f" and previous #{row['previous_id']}"
        head += ")"
    elif row.get("id") and row.get("baseline_id") == row["id"]:
        head += f" (recorded #{row['id']}, pinned as the baseline)"
    lines = [head]
    for k, d in row["deltas"].items():
        before = "" if d["before"] is None else f"  baseline {d['before']}ms ({d['pct']:+.1f}%)"
        if d.get("prev") is not None:
            before += f"  previous {d['prev']}ms ({d['prev_pct']:+.1f}%)"
        lines.append(f"  {'REGRESSION' if d['regression'] else 'ok':<10} {k:<24} {d['now']:>9}ms{before}")
    if row.get("id") and row.get("compared_to"):
        lines.append(f"  recorded as #{row['id']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the SYRAX benchmark suite.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--journal", help="journal to compare against and record into (default SYRAX_JOURNAL_FILE or none)")
    ap.add_argument("--pin-baseline", metavar="ID", help="human only: pin benchmark #ID (or 'latest') as the baseline, then exit")
    args = ap.parse_args(argv)
    path = args.journal or os.getenv("SYRAX_JOURNAL_FILE")
    if args.pin_baseline:
        if not path:
            sys.stderr.write("--pin-baseline needs --journal (or SYRAX_JOURNAL_FILE)\n")
            return 2
        j = Journal(path, recover=False)
        try:
            row = pin_baseline(j, None if args.pin_baseline == "latest" else int(args.pin_baseline))
        except (ValueError, RuntimeError) as e:
            sys.stderr.write(f"{e}\n")
            return 2
        finally:
            j.close()
        sys.stdout.write(f"pinned benchmark #{row['id']} ({row['status']}, git {row.get('git_head') or '?'}) as the baseline\n")
        return 0
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
