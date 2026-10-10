"""The rise ledger: whether SYRAX is getting better, measured, not claimed.

Every number is a query over the journal, opened read-only. Each metric
belongs to one of the five pillars of docs/EXECUTION_PLAN.md (brain,
evolution, memory, evidence, demonstration), says which direction is better,
and is computed for the last WINDOW_DAYS, for the WINDOW_DAYS before that,
and for all time. There is no status colour and no verdict: the numbers and
their definitions are the whole report. The milestones of the execution plan
are judged by these numbers.

    python -m syrax.rise [--journal config/journal.db] [--out ../docs/RISE.md] [--json out.json]

This file measures SYRAX, so its own releases may not change it (devloop.JUDGES).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from syrax.journal import BACKEND_ROOT, DEFAULT_FILE

REPO_ROOT = BACKEND_ROOT.parent
WINDOW_DAYS = 7
FULL_QUALITY_CASES = 10  # a quality run with fewer cases is a subset re-run, not a measurement of the whole suite
WEAK_CHECKS = ("task_success",)  # the check that only asks whether the task said SUCCESS
CHANGE_EVENTS = ("code.changed", "commit.created", "skill.created", "knowledge.stored")

Value = Tuple[Optional[float], str]  # (number or None when there is no evidence, how it was counted)


@dataclass
class Metric:
    id: str
    pillar: str
    label: str
    better: str  # "higher" | "lower" | "-" (context only)
    unit: str  # "%" | "count" | "attempts"
    definition: str
    fn: Callable[[sqlite3.Connection, float, float], Value]


def _one(c: sqlite3.Connection, sql: str, *args: Any) -> Any:
    return c.execute(sql, args).fetchone()[0]


def _share(num: int, den: int) -> Value:
    return (round(100.0 * num / den, 1), f"{num}/{den}") if den else (None, "no data")


def _count_events(type_: str) -> Callable[[sqlite3.Connection, float, float], Value]:
    def fn(c: sqlite3.Connection, t0: float, t1: float) -> Value:
        n = _one(c, "SELECT COUNT(*) FROM events WHERE type=? AND ts>=? AND ts<?", type_, t0, t1)
        return float(n), f"{n} {type_}"
    return fn


# ——— brain ———

def quality_pass_rate(c, t0, t1) -> Value:
    for r in c.execute("SELECT id, pass_rate, results FROM quality_runs WHERE ts>=? AND ts<? ORDER BY id DESC", (t0, t1)):
        n = len(json.loads(r[2] or "[]"))
        if n >= FULL_QUALITY_CASES:
            return float(r[1]), f"run #{r[0]}, {n} cases"
    return None, "no full quality run"


def _closed_machine_objectives(c, t0, t1) -> List[sqlite3.Row]:
    rows = c.execute("SELECT status, attempts, check_spec FROM objectives WHERE status IN ('DONE','BLOCKED') AND updated>=? AND updated<?",
                     (t0, t1)).fetchall()
    out = []
    for r in rows:
        kind = (json.loads(r[2] or "{}") or {}).get("kind", "task_success")
        if kind not in WEAK_CHECKS and kind != "human":
            out.append(r)
    return out


def objective_success(c, t0, t1) -> Value:
    rows = _closed_machine_objectives(c, t0, t1)
    return _share(sum(1 for r in rows if r[0] == "DONE"), len(rows))


def attempts_to_done(c, t0, t1) -> Value:
    done = [int(r[1] or 0) for r in _closed_machine_objectives(c, t0, t1) if r[0] == "DONE"]
    if not done:
        return None, "no machine-checked objective done"
    return float(statistics.median(done)), f"median of {len(done)}"


def tool_failure_share(c, t0, t1) -> Value:
    ok = _one(c, "SELECT COUNT(*) FROM events WHERE type='tool.completed' AND ts>=? AND ts<?", t0, t1)
    bad = _one(c, "SELECT COUNT(*) FROM events WHERE type='tool.failed' AND ts>=? AND ts<?", t0, t1)
    return _share(bad, ok + bad)


def unfinished_own_tasks(c, t0, t1) -> Value:
    done = _one(c, "SELECT COUNT(*) FROM tasks WHERE kind='autonomous' AND status IN ('SUCCESS','PARTIAL','FAILED') AND created>=? AND created<?", t0, t1)
    partial = _one(c, "SELECT COUNT(*) FROM tasks WHERE kind='autonomous' AND status IN ('PARTIAL','FAILED') AND created>=? AND created<?", t0, t1)
    return _share(partial, done)


# ——— evolution ———

def release_success(c, t0, t1) -> Value:
    attempts = _one(c, "SELECT COUNT(*) FROM events WHERE type='tool.started' AND json_extract(payload,'$.name')='release' AND ts>=? AND ts<?", t0, t1)
    commits = _one(c, "SELECT COUNT(*) FROM events WHERE type='commit.created' AND ts>=? AND ts<?", t0, t1)
    return _share(commits, attempts)


def live_tree_edits(c, t0, t1) -> Value:
    """Edits SYRAX's own (autonomous) tasks made in the running tree instead of
    an isolated worktree (M1). code.changed of an isolated task says so."""
    n = _one(c, "SELECT COUNT(*) FROM events e JOIN tasks t ON t.task_id=e.task_id WHERE e.type='code.changed' "
                "AND t.kind='autonomous' AND json_extract(e.payload,'$.path') IS NOT NULL "
                "AND COALESCE(json_extract(e.payload,'$.isolated'),0)=0 AND e.ts>=? AND e.ts<?", t0, t1)
    return float(n), f"{n} edits"


def review_rejections(c, t0, t1) -> Value:
    n = _one(c, "SELECT COUNT(*) FROM events WHERE type='review.completed' AND json_extract(payload,'$.approve')=0 AND ts>=? AND ts<?", t0, t1)
    return float(n), f"{n} rejected"


def experiments_run(c, t0, t1) -> Value:
    n = _one(c, "SELECT COUNT(*) FROM experiments WHERE ts>=? AND ts<?", t0, t1)
    return float(n), f"{n} experiments"


# ——— memory ———

def knowledge_used(c, t0, t1) -> Value:
    n = _one(c, "SELECT COUNT(*) FROM knowledge WHERE last_used>=? AND last_used<?", t0, t1)
    return float(n), f"{n} conclusions read back"


def knowledge_settled(c, t0, t1) -> Value:
    n = _one(c, "SELECT COUNT(*) FROM events WHERE type IN ('knowledge.reinforced','knowledge.contradiction') AND ts>=? AND ts<?", t0, t1)
    return float(n), f"{n} reinforced or contradicted"


# ——— evidence ———

def unbacked_claims(c, t0, t1) -> Value:
    """Own tasks whose final answer claims a change, while the task changed,
    committed and learned nothing. The patterns are the agent's own filters."""
    from syrax.agent import CLAIM, OWN_WORK_CLAIM

    rows = c.execute("SELECT task_id, result FROM tasks WHERE kind='autonomous' AND result IS NOT NULL AND created>=? AND created<?", (t0, t1)).fetchall()
    marks = ",".join("?" * len(CHANGE_EVENTS))
    n = 0
    for tid, result in rows:
        if not (CLAIM.search(result) or OWN_WORK_CLAIM.search(result)):
            continue
        if not _one(c, f"SELECT COUNT(*) FROM events WHERE task_id=? AND type IN ({marks})", tid, *CHANGE_EVENTS):
            n += 1
    return float(n), f"{n} of {len(rows)} own final answers"


def weak_closures(c, t0, t1) -> Value:
    rows = c.execute("SELECT check_spec FROM objectives WHERE status='DONE' AND updated>=? AND updated<?", (t0, t1)).fetchall()
    weak = sum(1 for (spec,) in rows if (json.loads(spec or "{}") or {}).get("kind", "task_success") in WEAK_CHECKS)
    return _share(weak, len(rows))


def gate_green(c, t0, t1) -> Value:
    total = _one(c, "SELECT COUNT(*) FROM verifications WHERE ts>=? AND ts<?", t0, t1)
    green = _one(c, "SELECT COUNT(*) FROM verifications WHERE status='GREEN' AND ts>=? AND ts<?", t0, t1)
    return _share(green, total)


def guard_refusals(c, t0, t1) -> Value:
    rel = _one(c, "SELECT COUNT(*) FROM events WHERE type='tool.failed' AND json_extract(payload,'$.name')='release' "
                  "AND json_extract(payload,'$.output') LIKE '%refused: refused:%' AND ts>=? AND ts<?", t0, t1)
    perm = _one(c, "SELECT COUNT(*) FROM events WHERE type='permission.refused' AND ts>=? AND ts<?", t0, t1)
    return float(rel + perm), f"{rel} release, {perm} permission"


# ——— demonstration ———

def published_matrix_age(c, t0, t1) -> Value:
    """Days between the end of the window and the newest generated capability
    matrix (read from its own header); a demonstration nobody refreshes ages."""
    path = REPO_ROOT / "docs" / "CAPABILITY_MATRIX.md"
    try:
        head = path.read_text(encoding="utf-8")[:400]
    except OSError:
        return None, "no capability matrix"
    m = re.search(r"Generated (\d{4}-\d{2}-\d{2})", head)
    if not m:
        return None, "matrix has no date"
    generated = time.mktime(time.strptime(m.group(1), "%Y-%m-%d"))
    if generated >= t1:
        return None, f"generated {m.group(1)}, after this window"
    return float(int((t1 - generated) // 86400)), f"generated {m.group(1)}"


METRICS: List[Metric] = [
    Metric("quality", "Brain", "Quality suite pass rate", "higher", "%", "Latest full quality run (at least 10 cases) in the window: real tasks through the real brains, judged by checks on disk and in the journal.", quality_pass_rate),
    Metric("objective_success", "Brain", "Machine-checked objectives done", "higher", "%", "Objectives closed in the window whose check is evidence (not task_success): DONE out of DONE + BLOCKED.", objective_success),
    Metric("attempts", "Brain", "Attempts per objective done", "lower", "attempts", "Median attempts of the machine-checked objectives closed DONE in the window.", attempts_to_done),
    Metric("tool_failures", "Brain", "Tool calls that failed", "lower", "%", "tool.failed out of all finished tool calls in the window (refusals by a guard count as failures).", tool_failure_share),
    Metric("unfinished", "Brain", "Own tasks left unfinished", "lower", "%", "Autonomous tasks that ended PARTIAL (step limit, loop stop) or FAILED, out of all finished ones.", unfinished_own_tasks),
    Metric("own_commits", "Evolution", "Commits SYRAX made to itself", "higher", "count", "commit.created: a change that passed the gate, a second brain's review, and was committed by SYRAX's release.", _count_events("commit.created")),
    Metric("release_success", "Evolution", "Releases that landed", "higher", "%", "commit.created out of release calls in the window.", release_success),
    Metric("live_tree_edits", "Evolution", "Own edits in the running tree", "lower", "count", "Editor edits by SYRAX's own tasks that landed in the running tree instead of the task's isolated worktree (M1; every edit before it counts).", live_tree_edits),
    Metric("rollbacks", "Evolution", "Changes rolled back", "lower", "count", "rollback.created: an own change that failed the gate or the review, or a task that ended without releasing its edits.", _count_events("rollback.created")),
    Metric("review_rejections", "Evolution", "Changes a second brain rejected", "-", "count", "review.completed with approve false.", review_rejections),
    Metric("experiments", "Evolution", "Experiments run", "higher", "count", "Rows in the experiments table: baseline against candidate, verdict computed from numbers.", experiments_run),
    Metric("knowledge_stored", "Memory", "Conclusions stored", "-", "count", "knowledge.stored events (verified conclusions with sources).", _count_events("knowledge.stored")),
    Metric("knowledge_used", "Memory", "Conclusions read back", "higher", "count", "Stored conclusions whose last use falls in the window: memory that was used, not only kept.", knowledge_used),
    Metric("knowledge_settled", "Memory", "Conclusions reinforced or contradicted", "-", "count", "knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.", knowledge_settled),
    Metric("unbacked_claims", "Evidence", "Final answers claiming work not done", "lower", "count", "Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.", unbacked_claims),
    Metric("weak_closures", "Evidence", "Objectives closed on words", "lower", "%", "Objectives closed DONE whose check was only task_success.", weak_closures),
    Metric("gate_green", "Evidence", "Gate verdicts GREEN", "higher", "%", "Journaled verifications that were GREEN.", gate_green),
    Metric("guard_refusals", "Evidence", "Guards that held", "-", "count", "Releases refused for touching a judge or an existing test, and calls refused by the permission gate.", guard_refusals),
    Metric("matrix_age", "Demonstration", "Days since the capability matrix was generated", "lower", "days", "Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.", published_matrix_age),
]
PILLARS = ("Brain", "Evolution", "Memory", "Evidence", "Demonstration")


def measure(journal_path: Path = DEFAULT_FILE, now: Optional[float] = None) -> Dict[str, Any]:
    now = now or time.time()
    w = WINDOW_DAYS * 86400
    windows = {"last": (now - w, now), "previous": (now - 2 * w, now - w), "all": (0.0, now)}
    c = sqlite3.connect(f"file:{Path(journal_path).as_posix()}?mode=ro", uri=True)
    try:
        span = c.execute("SELECT MIN(ts), MAX(ts), COUNT(*) FROM events").fetchone()
        rows = []
        for m in METRICS:
            vals = {k: m.fn(c, t0, t1) for k, (t0, t1) in windows.items()}
            rows.append({"id": m.id, "pillar": m.pillar, "label": m.label, "better": m.better, "unit": m.unit,
                         "definition": m.definition, **{k: {"value": v, "detail": d} for k, (v, d) in vals.items()}})
    finally:
        c.close()
    return {"generated": now, "window_days": WINDOW_DAYS, "journal": str(journal_path),
            "events": span[2], "first_event": span[0], "last_event": span[1], "metrics": rows}


def _fmt(v: Optional[float], unit: str, detail: str) -> str:
    if v is None:
        return "—"
    num = f"{v:g}" if unit != "%" else f"{v:g} %"
    return f"{num} ({detail})" if unit in ("%", "attempts") else num


def trend(row: dict) -> str:
    """Plain words for the change from the previous window to the last one."""
    a, b = row["previous"]["value"], row["last"]["value"]
    if a is None or b is None or row["better"] == "-":
        return "—"
    if a == b:
        return "same"
    return "better" if (b > a) == (row["better"] == "higher") else "worse"


def render(data: dict, head: str = "?") -> str:
    t = lambda ts: time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"
    lines = [
        "# SYRAX rise ledger", "",
        f"Generated {t(data['generated'])} by `python -m syrax.rise` at commit `{head}` from the journal "
        f"({data['events']} events, {t(data['first_event'])} to {t(data['last_event'])}). Every number is a read-only "
        "query over the journal; nothing here is typed by hand. **Last** is the last "
        f"{data['window_days']} days, **previous** the {data['window_days']} days before, **trend** compares the two in the "
        "metric's own better direction. A dash means there is no evidence, which is reported as such.", "",
        "The milestones in [EXECUTION_PLAN.md](EXECUTION_PLAN.md) are judged by these numbers.", "",
    ]
    for pillar in PILLARS:
        lines += [f"## {pillar}", "", "| Metric | Last | Previous | All time | Better when | Trend |", "|---|---|---|---|---|---|"]
        defs = []
        for r in data["metrics"]:
            if r["pillar"] != pillar:
                continue
            cells = [_fmt(r[k]["value"], r["unit"], r[k]["detail"]) for k in ("last", "previous", "all")]
            lines.append(f"| {r['label']} | {cells[0]} | {cells[1]} | {cells[2]} | {r['better']} | {trend(r)} |")
            defs.append(f"- **{r['label']}**: {r['definition']}")
        lines += [""] + defs + [""]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--journal", default=str(DEFAULT_FILE))
    ap.add_argument("--out", default=str(REPO_ROOT / "docs" / "RISE.md"))
    ap.add_argument("--json")
    ap.add_argument("--head")
    a = ap.parse_args(argv)
    head = a.head
    if not head:
        import subprocess
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True,
                              encoding="utf-8").stdout.strip() or "?"
    data = measure(Path(a.journal))
    Path(a.out).write_text(render(data, head), encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"{a.out}: {len(data['metrics'])} metrics over {data['events']} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
