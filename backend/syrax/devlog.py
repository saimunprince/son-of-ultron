"""The devlog (M6, public demonstration): one entry per day SYRAX ran, generated
from the journal and git, never typed by hand.

Each day lists what was finished and what failed, the objectives closed, the
quality run, the incidents (stalls, interrupted tasks, rollbacks, false claims
sent back, restarts) and that day's commits, SYRAX's own apart from the human's.
It is written next to docs/RISE.md by the daily ledger release (ledger.py), so
it is published the same way: in an isolated worktree, through the gate.

CLI: python -m syrax.devlog --out ../docs/DEVLOG.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from syrax.journal import BACKEND_ROOT, Journal

REPO_ROOT = BACKEND_ROOT.parent
MAX_DAYS = 60
SYRAX_AUTHOR = "SYRAX"


def git_commits(root: Path, since: float, until: float) -> List[Dict[str, str]]:
    """Commits in [since, until): short hash, author, subject. Empty when git is unavailable."""
    try:
        iso = lambda ts: dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")  # local time, as git reads it
        out = subprocess.run(["git", "log", f"--since={iso(since)}", f"--until={iso(until)}", "--format=%h|%an|%s"],
                             cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for line in (out.stdout or "").splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            rows.append({"hash": parts[0], "author": parts[1], "subject": parts[2]})
    return rows


def _day_bounds(day: dt.date) -> tuple:
    start = dt.datetime.combine(day, dt.time.min).timestamp()
    return start, start + 86400


def entry(journal: Journal, day: dt.date, commits: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """What one day held, or None when SYRAX did not run that day."""
    start, end = _day_bounds(day)
    events = journal.events_between(start, end - 0.001, limit=10000)
    if not events:
        return None
    kinds = Counter(e["type"] for e in events)
    closed = []
    for e in events:
        if e["type"] == "objective.completed":
            o = journal.objective(e["payload"].get("objective_id")) or {}
            closed.append(f"#{e['payload'].get('objective_id')} {str(o.get('goal') or '')[:90]}")
    runs = [r for r in journal.quality_runs(limit=50) if start <= r["ts"] < end]
    quality = None
    if runs:
        last = max(runs, key=lambda r: r["ts"])
        quality = {"id": last["id"], "pass_rate": last["pass_rate"], "cases": len(last["results"]),
                   "failed": [x["id"] for x in last["results"] if not x.get("ok")]}
    return {
        "day": day.isoformat(),
        "events": len(events),
        "finished": kinds.get("task.completed", 0),
        "failed": kinds.get("task.failed", 0),
        "closed": closed,
        "quality": quality,
        "incidents": {"stalls": kinds.get("stall.recovered", 0), "interrupted": kinds.get("task.interrupted", 0),
                      "rollbacks": kinds.get("rollback.created", 0), "claims_sent_back": kinds.get("claim.rejected", 0),
                      "restarts": kinds.get("restart.requested", 0)},
        "own_commits": [c for c in commits if c["author"] == SYRAX_AUTHOR],
        "human_commits": [c for c in commits if c["author"] != SYRAX_AUTHOR],
    }


def entries(journal: Journal, now: Optional[float] = None, root: Path = REPO_ROOT,
            commits_of: Optional[Callable[[float, float], List[Dict[str, str]]]] = None) -> List[Dict[str, Any]]:
    """One entry per day SYRAX ran, newest first, back to its first journaled event (at most MAX_DAYS)."""
    now = now or time.time()
    commits_of = commits_of or (lambda a, b: git_commits(root, a, b))
    first = journal.events_between(0, now, limit=1)
    if not first:
        return []
    day, oldest = dt.date.fromtimestamp(now), dt.date.fromtimestamp(first[0]["ts"])
    out = []
    while day >= oldest and len(out) < MAX_DAYS:
        start, end = _day_bounds(day)
        e = entry(journal, day, commits_of(start, min(end, now)))
        if e is not None:
            out.append(e)
        day -= dt.timedelta(days=1)
    return out


def render(days: List[Dict[str, Any]], head: str, generated: Optional[str] = None) -> str:
    generated = generated or time.strftime("%Y-%m-%d %H:%M %z")
    lines = ["# SYRAX devlog", "",
             f"Generated {generated} by `python -m syrax.devlog` at commit `{head}`, from the journal and git: one entry per day "
             "SYRAX ran, newest first. Nothing here is typed by hand; the numbers behind the trends are in [RISE.md](RISE.md).", ""]
    for d in days:
        lines += [f"## {d['day']}", ""]
        lines.append(f"- Tasks: {d['finished']} finished, {d['failed']} failed ({d['events']} journal events).")
        if d["closed"]:
            lines.append(f"- Objectives closed: {len(d['closed'])}")
            lines += [f"  - {c}" for c in d["closed"][:8]]
        q = d["quality"]
        if q:
            lines.append(f"- Quality run #{q['id']}: {q['pass_rate']} % of {q['cases']} cases"
                         + (f"; failed: {', '.join(q['failed'])}" if q["failed"] else "") + ".")
        inc = {k: v for k, v in d["incidents"].items() if v}
        if inc:
            lines.append("- Incidents: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in inc.items()) + ".")
        if d["own_commits"]:
            lines.append(f"- Commits SYRAX made to itself: {len(d['own_commits'])}")
            lines += [f"  - `{c['hash']}` {c['subject'][:100]}" for c in d["own_commits"]]
        if d["human_commits"]:
            lines.append(f"- Commits by its maintainers: {len(d['human_commits'])}")
            lines += [f"  - `{c['hash']}` {c['subject'][:100]}" for c in d["human_commits"][:25]]
            if len(d["human_commits"]) > 25:
                lines.append(f"  - and {len(d['human_commits']) - 25} more")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def head_of(root: Path = REPO_ROOT) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=10).stdout.strip() or "?"
    except (OSError, subprocess.TimeoutExpired):
        return "?"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Generate docs/DEVLOG.md from the journal and git")
    ap.add_argument("--journal", default=str(BACKEND_ROOT / "config" / "journal.db"))
    ap.add_argument("--out", default=str(REPO_ROOT / "docs" / "DEVLOG.md"))
    args = ap.parse_args(argv)
    j = Journal(Path(args.journal), recover=False)
    try:
        days = entries(j)
        Path(args.out).write_text(render(days, head_of()), encoding="utf-8", newline="\n")
    finally:
        j.close()
    print(f"{args.out}: {len(days)} day(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
