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

from syrax.journal import BACKEND_ROOT, DEFAULT_FILE, TERMINAL

REPO_ROOT = BACKEND_ROOT.parent
WINDOW_DAYS = 7
FULL_QUALITY_CASES = 10  # a quality run with fewer cases is a subset re-run, not a measurement of the whole suite
WEAK_CHECKS = ("task_success",)  # the check that only asks whether the task said SUCCESS
CHANGE_EVENTS = ("code.changed", "commit.created", "skill.created", "knowledge.stored")
CLEANUP_REASON = "task ended without a committed release"  # core._clean_repo_after_task: not a verdict on the change
TASK_END_EVENTS = ("task.completed", "task.failed", "task.cancelled", "task.interrupted")

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

FULL_SHARE = 0.9  # of the largest run so far: the suite grows (52 cases on 10-22, 67 on 10-26), a rotation does not


def quality_pass_rate(c, t0, t1) -> Value:
    """The latest full run in the window. A run is full when it has at least FULL_QUALITY_CASES cases and at least
    FULL_SHARE of the largest run recorded up to it: the 12-case rotation (run #86, 100 %) is a subset of the
    67-case suite, not its pass rate."""
    latest, largest = None, 0
    for r in c.execute("SELECT id, ts, pass_rate, json_array_length(results) FROM quality_runs WHERE ts<? ORDER BY id", (t1,)):
        n = int(r[3] or 0)
        largest = max(largest, n)
        if r[1] >= t0 and n >= FULL_QUALITY_CASES and n >= FULL_SHARE * largest:
            latest = (float(r[2]), f"run #{r[0]}, {n} cases")
    return latest or (None, "no full quality run")


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
    """Failed tool calls among calls that ran: a call the guard refused never ran, and a call refused for the caller's
    own mistake (journal.misuse: a wrong path, a date in the past, an unsupported claim to `learn`) is no failure of
    the tool (2026-10-30: both counted, and the drift monitor read them as a decline)."""
    from syrax.journal import misuse

    ok = _one(c, "SELECT COUNT(*) FROM events WHERE type='tool.completed' AND ts>=? AND ts<?", t0, t1)
    bad = 0
    for name, refused, output in c.execute(
            "SELECT json_extract(payload, '$.name'), json_extract(payload, '$.refused'), json_extract(payload, '$.output') "
            "FROM events WHERE type='tool.failed' AND ts>=? AND ts<?", (t0, t1)):
        if not refused and not misuse(name, output):
            bad += 1
    return _share(bad, ok + bad)


def unfinished_own_tasks(c, t0, t1) -> Value:
    done = _one(c, "SELECT COUNT(*) FROM tasks WHERE kind='autonomous' AND status IN ('SUCCESS','PARTIAL','FAILED') AND created>=? AND created<?", t0, t1)
    partial = _one(c, "SELECT COUNT(*) FROM tasks WHERE kind='autonomous' AND status IN ('PARTIAL','FAILED') AND created>=? AND created<?", t0, t1)
    return _share(partial, done)


def regression_rate(c, t0, t1) -> Value:
    total = _one(c, "SELECT COUNT(*) FROM quality_runs WHERE ts>=? AND ts<?", t0, t1)
    bad = _one(c, "SELECT COUNT(*) FROM quality_runs WHERE status='REGRESSION' AND ts>=? AND ts<?", t0, t1)
    return _share(bad, total)


def repeated_failures(c, t0, t1) -> Value:
    """Objectives with two or more attempts whose progress.attempts_log (autonomy) holds two
    attempts that were not DONE and went about it with the same strategy fingerprint."""
    rows = c.execute("SELECT progress FROM objectives WHERE attempts>=2 AND updated>=? AND updated<?", (t0, t1)).fetchall()
    n = 0
    for (prog,) in rows:
        log = ((json.loads(prog or "{}") or {}).get("attempts_log")) or []
        failed = [tuple(a.get("strategy") or []) for a in log if a.get("verdict") != "DONE"]
        if len(failed) != len(set(failed)):
            n += 1
    return _share(n, len(rows))


def _verified_objective_tasks(c, t0, t1) -> List[List[str]]:
    """For each objective closed DONE in the window by a machine check: the ids of the tasks that
    worked on it (progress.attempts_log, evidence.task_id, last_task_id; autonomy writes all three)."""
    rows = c.execute("SELECT check_spec, progress, evidence, last_task_id FROM objectives WHERE status='DONE' AND updated>=? AND updated<?",
                     (t0, t1)).fetchall()
    out = []
    for spec, prog, ev, last in rows:
        kind = (json.loads(spec or "{}") or {}).get("kind", "task_success")
        if kind in WEAK_CHECKS or kind == "human":
            continue
        ids = {a.get("task_id") for a in ((json.loads(prog or "{}") or {}).get("attempts_log") or [])}
        ids |= {(json.loads(ev or "{}") or {}).get("task_id"), last}
        out.append(sorted(i for i in ids if i))
    return out


def _median_per_verified_objective(c, t0, t1, per_tasks: Callable[[sqlite3.Connection, List[str]], float], digits: int) -> Value:
    groups = _verified_objective_tasks(c, t0, t1)
    per = [per_tasks(c, ids) for ids in groups if ids]
    if not per:
        return None, "no verified objective with a task"
    skipped = len(groups) - len(per)
    return round(float(statistics.median(per)), digits), f"median of {len(per)}" + (f", {skipped} closed without a task" if skipped else "")


def brain_calls_per_objective(c, t0, t1) -> Value:
    def calls(c, ids):
        return _one(c, f"SELECT COUNT(*) FROM events WHERE type='brain.answered' AND task_id IN ({','.join('?' * len(ids))})", *ids)
    return _median_per_verified_objective(c, t0, t1, calls, 0)


def minutes_per_objective(c, t0, t1) -> Value:
    def minutes(c, ids):
        marks = ",".join("?" * len(ids))
        ends = ",".join("?" * len(TASK_END_EVENTS))
        secs = _one(c, f"SELECT COALESCE(SUM(COALESCE((SELECT MIN(e.ts) FROM events e WHERE e.task_id=t.task_id AND e.type IN ({ends})), t.updated) - t.created), 0) "
                       f"FROM tasks t WHERE t.task_id IN ({marks})", *TASK_END_EVENTS, *ids)
        return secs / 60.0
    return _median_per_verified_objective(c, t0, t1, minutes, 1)


# ——— evolution ———

def release_success(c, t0, t1) -> Value:
    """Every release that reaches the gate runs it exactly once (devloop._release), whether it was
    called as a tool or directly by the daily ledger publish; a release refused before the gate
    (scope, judge, test guard, preflight) is a failed tool call. Both are attempts."""
    gated = _one(c, "SELECT COUNT(*) FROM events WHERE type='verification.completed' AND ts>=? AND ts<?", t0, t1)
    refused = _one(c, "SELECT COUNT(*) FROM events WHERE type='tool.failed' AND json_extract(payload,'$.name')='release' AND ts>=? AND ts<?", t0, t1)
    commits = _one(c, "SELECT COUNT(*) FROM events WHERE type='commit.created' AND ts>=? AND ts<?", t0, t1)
    return _share(commits, gated + refused)


def _commits(docs_only: bool) -> Callable[[sqlite3.Connection, float, float], Value]:
    """commit.created lists its files repo-relative with forward slashes (devloop.commit)."""
    outside_docs = "EXISTS (SELECT 1 FROM json_each(payload,'$.files') WHERE value NOT LIKE 'docs/%')"

    def fn(c: sqlite3.Connection, t0: float, t1: float) -> Value:
        n = _one(c, f"SELECT COUNT(*) FROM events WHERE type='commit.created' AND {'NOT ' if docs_only else ''}{outside_docs} AND ts>=? AND ts<?", t0, t1)
        return float(n), f"{n} commits"
    return fn


def _rollbacks(cleanup: bool) -> Callable[[sqlite3.Connection, float, float], Value]:
    def fn(c: sqlite3.Connection, t0: float, t1: float) -> Value:
        n = _one(c, f"SELECT COUNT(*) FROM events WHERE type='rollback.created' AND COALESCE(json_extract(payload,'$.reason'),'') {'=' if cleanup else '<>'} ? "
                    "AND ts>=? AND ts<?", CLEANUP_REASON, t0, t1)
        return float(n), f"{n} rollback.created"
    return fn


# Audit 2026-10-27 (open item 2): objective_success counts every machine-checked closure, and most of them were
# research objectives (knowledge_stored: 13 "biggest measured limitation" objectives in a week, none led to code).
# These are the checks an objective can only pass once a change landed and was measured.
CHANGE_CHECKS = ("change_released", "quality_case_passes", "quality_recovered", "tool_reliability", "repro_proven",
                 "benchmark_recovered", "verification_green")


def change_objectives_done(c, t0, t1) -> Value:
    rows = c.execute("SELECT check_spec FROM objectives WHERE status='DONE' AND updated>=? AND updated<?", (t0, t1)).fetchall()
    n = sum(1 for (spec,) in rows if (json.loads(spec or "{}") or {}).get("kind") in CHANGE_CHECKS)
    return float(n), f"{n} of {len(rows)} objectives done needed a landed change"


def _commit_authors(t0: float, t1: float) -> Optional[List[str]]:
    import subprocess

    try:
        r = subprocess.run(["git", "log", f"--since=@{int(t0)}", f"--until=@{int(t1)}", "--format=%an"], cwd=str(REPO_ROOT),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return None if r.returncode else [a for a in r.stdout.splitlines() if a.strip()]


def human_commit_share(c, t0, t1) -> Value:
    """Commits in the repository in the window that a person made (any author but SYRAX), out of all commits: the
    audit found 88.7 % of 14 days' commits were human, which no metric showed."""
    authors = _commit_authors(t0, t1)
    if authors is None:
        return None, "git log unavailable"
    return _share(sum(1 for a in authors if a.strip().lower() != "syrax"), len(authors))


def human_interventions(c, t0, t1) -> Value:
    asked = _one(c, "SELECT COUNT(*) FROM events WHERE type='ask' AND ts>=? AND ts<?", t0, t1)
    perm = _one(c, "SELECT COUNT(*) FROM events WHERE type='permission.authorized' AND json_extract(payload,'$.authorized_by')='human' AND ts>=? AND ts<?", t0, t1)
    obj = _one(c, "SELECT COUNT(*) FROM events WHERE type LIKE 'objective.%' AND (json_extract(payload,'$.note') LIKE 'human:%' "
                  "OR json_extract(payload,'$.note') LIKE 'human dismissed%') AND ts>=? AND ts<?", t0, t1)
    stopped = _one(c, "SELECT COUNT(*) FROM events WHERE type='task.cancelled' AND json_extract(payload,'$.error') LIKE '%by human%' AND ts>=? AND ts<?", t0, t1)
    return float(asked + perm + obj + stopped), f"{asked} asked, {perm} permissions, {obj} objectives, {stopped} tasks stopped"


UNDO_WITHIN_S = 600  # an undo this soon after a request counts against that request


def smooth_requests(c, t0, t1) -> Value:
    """EVOLUTION_PLAN direction 298 (human-impact evaluation): the human's requests (conversation tasks) that ended in
    the window and cost them nothing more: SUCCESS, no question asked, no permission prompted or refused, and the next
    request was neither a dispute of it (claims.is_dispute) nor an undo within UNDO_WITHIN_S."""
    from syrax.claims import is_dispute

    keys = ("task_id", "goal", "status", "created", "updated")
    rows = [dict(zip(keys, r)) for r in c.execute(
        "SELECT task_id, goal, status, created, updated FROM tasks WHERE kind='conversation' "
        "AND status IN ('SUCCESS','PARTIAL','FAILED','CANCELLED','BLOCKED','INTERRUPTED') ORDER BY created")]
    ends = [r for r in rows if t0 <= r["updated"] < t1]
    if not ends:
        return None, "no request of the human ended in the window"
    after = {r["task_id"]: rows[i + 1] if i + 1 < len(rows) else None for i, r in enumerate(rows)}
    why = {"not SUCCESS": 0, "asked": 0, "permission": 0, "disputed": 0, "undone": 0}
    smooth = 0
    for r in ends:
        t = r["task_id"]
        types = {x[0] for x in c.execute("SELECT type FROM events WHERE task_id=? AND type IN ('ask','permission.authorized','permission.refused')", (t,))}
        nxt = after.get(t)
        undone = bool(nxt and nxt["created"] - r["updated"] <= UNDO_WITHIN_S and c.execute(
            "SELECT 1 FROM events WHERE task_id=? AND type='tool.started' AND json_extract(payload,'$.name')='undo' LIMIT 1",
            (nxt["task_id"],)).fetchone())
        flags = {"not SUCCESS": r["status"] != "SUCCESS", "asked": "ask" in types,
                 "permission": bool(types & {"permission.authorized", "permission.refused"}),
                 "disputed": bool(nxt and is_dispute(nxt["goal"])), "undone": undone}
        for k, v in flags.items():
            why[k] += v
        smooth += not any(flags.values())
    v, _ = _share(smooth, len(ends))
    costs = ", ".join(f"{n} {k}" for k, n in why.items() if n)
    return v, f"{smooth} of {len(ends)} requests" + (f"; {costs}" if costs else "")


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
    from syrax.claims import CLAIM, OWN_WORK_CLAIM

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


def interrupted_resolved(c, t0, t1) -> Value:
    """Tasks a crash or restart interrupted in the window that later ended: resumed to an end
    (recovery.resumed, then completed or failed) or dismissed (task.cancelled). Their status now."""
    marks = ",".join("?" * len(TERMINAL))
    total = _one(c, "SELECT COUNT(DISTINCT task_id) FROM events WHERE type='task.interrupted' AND ts>=? AND ts<?", t0, t1)
    ended = _one(c, f"SELECT COUNT(*) FROM tasks WHERE status IN ({marks}) AND task_id IN "
                    "(SELECT DISTINCT task_id FROM events WHERE type='task.interrupted' AND ts>=? AND ts<?)", *sorted(TERMINAL), t0, t1)
    return _share(ended, total)


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
    Metric("quality", "Brain", "Quality suite pass rate", "higher", "%", "Latest full quality run in the window (at least 10 cases and 90 % of the largest run so far; a rotation subset is not the suite): real tasks through the real brains, judged by checks on disk and in the journal.", quality_pass_rate),
    Metric("objective_success", "Brain", "Machine-checked objectives done", "higher", "%", "Objectives closed in the window whose check is evidence (not task_success): DONE out of DONE + BLOCKED.", objective_success),
    Metric("change_objectives", "Brain", "Objectives done that needed a landed change", "higher", "count", "Objectives closed DONE in the window whose check passes only after a change landed and was measured (a release, a quality case or run, tool reliability, a repro hunt, a benchmark, a GREEN gate); research objectives are not counted.", change_objectives_done),
    Metric("attempts", "Brain", "Attempts per objective done", "lower", "attempts", "Median attempts of the machine-checked objectives closed DONE in the window.", attempts_to_done),
    Metric("repeated_failures", "Brain", "Objectives that repeated a failed strategy", "lower", "%", "Objectives with two or more attempts, updated in the window, whose attempts_log holds two attempts that were not DONE and used the same strategy fingerprint (the distinct tool calls of the attempt, as autonomy records them), out of all objectives with two or more attempts.", repeated_failures),
    Metric("brain_calls_per_objective", "Brain", "Brain calls per verified objective (median)", "lower", "calls", "Median over the machine-checked objectives closed DONE in the window of the brain.answered events of all their tasks (every attempt, from attempts_log, evidence.task_id and last_task_id); objectives closed without a task are left out and counted in the detail.", brain_calls_per_objective),
    Metric("minutes_per_objective", "Brain", "Minutes per verified objective (median)", "lower", "minutes", "Median over the same objectives of the wall time of all their tasks, each from its start to the event that ended it (completed, failed, cancelled or interrupted; its last update when none did).", minutes_per_objective),
    Metric("tool_failures", "Brain", "Tool calls that failed", "lower", "%", "tool.failed out of all finished tool calls in the window; calls a guard refused and calls refused for the caller's own mistake (journal.misuse) are left out. This PC's own rows only.", tool_failure_share),
    Metric("unfinished", "Brain", "Own tasks left unfinished", "lower", "%", "Autonomous tasks that ended PARTIAL (step limit, loop stop) or FAILED, out of all finished ones.", unfinished_own_tasks),
    Metric("regressions", "Brain", "Quality runs that regressed", "lower", "%", "Quality runs in the window (full suite or a subset re-run) whose status was REGRESSION: a pass rate below the run they were compared to, out of all quality runs.", regression_rate),
    Metric("own_commits", "Evolution", "Commits SYRAX made to itself", "higher", "count", "commit.created that changed a file outside docs/: code, tests or config that passed the gate and a second brain's review and was committed by SYRAX's release. The daily regeneration of the docs is counted apart.", _commits(docs_only=False)),
    Metric("docs_commits", "Evolution", "Commits that only regenerated docs", "-", "count", "commit.created whose files are all under docs/: the daily publish of the ledger, the devlog, the archive and the capability matrix through the same gate and review, with no code changed.", _commits(docs_only=True)),
    Metric("release_success", "Evolution", "Releases that landed", "higher", "%", "commit.created out of release attempts in the window: gate runs (verification.completed; every release that reaches the gate runs it once, the daily ledger publish included, which releases without a tool call) plus release calls refused before the gate (tool.failed).", release_success),
    Metric("live_tree_edits", "Evolution", "Own edits in the running tree", "lower", "count", "Editor edits by SYRAX's own tasks that landed in the running tree instead of the task's isolated worktree (M1; every edit before it counts).", live_tree_edits),
    Metric("rollbacks", "Evolution", "Changes rolled back by the gate or the review", "lower", "count", "rollback.created by a release: the gate was BLOCKED, a second brain rejected the change, or no second brain could review it (any reason but the end-of-task cleanup).", _rollbacks(cleanup=False)),
    Metric("cleanups", "Evolution", "Unreleased edits cleaned up after a task", "lower", "count", "rollback.created with reason \"task ended without a committed release\": a task left edits it never released (step limit, failure, cancel) and they were restored or kept as a diff; no verdict on the change.", _rollbacks(cleanup=True)),
    Metric("review_rejections", "Evolution", "Changes a second brain rejected", "-", "count", "review.completed with approve false.", review_rejections),
    Metric("experiments", "Evolution", "Experiments run", "higher", "count", "Rows in the experiments table: baseline against candidate, verdict computed from numbers.", experiments_run),
    Metric("human_interventions", "Evolution", "Human interventions", "lower", "count", "Times a person had to step in: ask events (SYRAX asked a question), permission.authorized with authorized_by human, objective.* events whose note a human wrote (\"human: ...\", a dismissal), and task.cancelled by a human (aborted, removed from the queue or dismissed).", human_interventions),
    Metric("smooth_requests", "Evolution", "The human's requests that cost them nothing more", "higher", "%", "Conversation tasks that ended in the window SUCCESS, with no question asked, no permission prompted or refused, and not disputed or undone by the next request (an undo within 10 minutes), out of all that ended: what SYRAX costs the human, not only whether its tasks pass (direction 298).", smooth_requests),
    Metric("human_commits", "Evolution", "Commits a person made", "-", "%", "Commits in the repository in the window by any author but SYRAX, out of all commits (git log): how much of the change still comes from people.", human_commit_share),
    Metric("knowledge_stored", "Memory", "Conclusions stored", "-", "count", "knowledge.stored events (verified conclusions with sources).", _count_events("knowledge.stored")),
    Metric("knowledge_used", "Memory", "Conclusions read back", "higher", "count", "Stored conclusions whose last use falls in the window: memory that was used, not only kept.", knowledge_used),
    Metric("knowledge_settled", "Memory", "Conclusions reinforced or contradicted", "-", "count", "knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.", knowledge_settled),
    Metric("unbacked_claims", "Evidence", "Final answers claiming work not done", "lower", "count", "Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.", unbacked_claims),
    Metric("claims_rejected", "Evidence", "False claims sent back", "-", "count", "claim.rejected: a final answer claimed work its task did not do and was sent back to be rewritten (journaled since M3).", _count_events("claim.rejected")),
    Metric("weak_closures", "Evidence", "Objectives closed on words", "lower", "%", "Objectives closed DONE whose check was only task_success.", weak_closures),
    Metric("gate_green", "Evidence", "Gate verdicts GREEN", "higher", "%", "Journaled verifications that were GREEN.", gate_green),
    Metric("guard_refusals", "Evidence", "Guards that held", "-", "count", "Releases refused for touching a judge or an existing test, and calls refused by the permission gate.", guard_refusals),
    Metric("interrupted_resolved", "Evidence", "Interrupted tasks resumed or dismissed", "higher", "%", "Tasks marked task.interrupted in the window (a crash or restart cut them) that have since reached a terminal status: resumed and finished, failed, or dismissed by a human (task.cancelled), out of all tasks interrupted in the window.", interrupted_resolved),
    Metric("matrix_age", "Demonstration", "Days since the capability matrix was generated", "lower", "days", "Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.", published_matrix_age),
]
PILLARS = ("Brain", "Evolution", "Memory", "Evidence", "Demonstration")


IMPORTED = {  # tables that hold rows merged in from another PC's journal (syrax-tools/import_windows_journal.py)
    "events": "id > 0", "checkpoints": "id > 0", "objectives": "id > 0", "knowledge": "id > 0", "experiments": "id > 0",
    "tasks": "last_event_id IS NULL OR last_event_id >= 0",
}


def _own_rows(c: sqlite3.Connection) -> None:
    """Make this connection see only this PC's own rows: a TEMP VIEW of the same name shadows each table that can hold
    merged rows (their ids are shifted below zero). 2026-10-30: after the Windows journal was merged, a "last 3 days"
    window mixed both machines, and the drift monitor compared Windows days with Linux days."""
    for table, own in IMPORTED.items():
        c.execute(f"CREATE TEMP VIEW IF NOT EXISTS {table} AS SELECT * FROM main.{table} WHERE {own}")


def measure(journal_path: Path = DEFAULT_FILE, now: Optional[float] = None) -> Dict[str, Any]:
    now = now or time.time()
    w = WINDOW_DAYS * 86400
    windows = {"last": (now - w, now), "previous": (now - 2 * w, now - w), "all": (0.0, now)}
    c = sqlite3.connect(f"file:{Path(journal_path).as_posix()}?mode=ro", uri=True)
    _own_rows(c)  # this PC's own record; merged history stays readable through the journal itself
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


DRIFT_DAYS = 1.0  # the window of the drift check: three consecutive days


def _worse(a: float, b: float, better: str) -> bool:
    return b < a if better == "higher" else b > a


def _material(first: float, last: float, unit: str) -> bool:
    """A change big enough to call drift: 5 points for a share, 50 % (and 2) for a count, 20 % otherwise."""
    change = abs(last - first)
    if unit == "%":
        return change >= 5.0
    if unit == "count":
        return change >= max(2.0, 0.5 * max(abs(first), 1.0))
    return change >= 0.2 * max(abs(first), 1e-9)


def drift(journal_path: Path = DEFAULT_FILE, now: Optional[float] = None, days: float = DRIFT_DAYS) -> List[dict]:
    """Metrics that got worse in each of three consecutive windows of `days`, by a material amount (EVOLUTION_PLAN wave
    2, directions 265 drift detection, 297 value-drift monitoring). Among them are the value metrics: unbacked claims,
    guard refusals, review rejections. A single bad day is noise and is not reported; two worse steps in a row are."""
    now = now or time.time()
    w = days * 86400
    windows = [(now - 3 * w, now - 2 * w), (now - 2 * w, now - w), (now - w, now)]
    c = sqlite3.connect(f"file:{Path(journal_path).as_posix()}?mode=ro", uri=True)
    _own_rows(c)
    out = []
    try:
        for m in METRICS:
            if m.better not in ("higher", "lower"):
                continue
            vals = [m.fn(c, t0, t1)[0] for t0, t1 in windows]
            if any(v is None for v in vals):
                continue
            a, b, z = vals
            if _worse(a, b, m.better) and _worse(b, z, m.better) and _material(a, z, m.unit):
                out.append({"metric": m.id, "label": m.label, "pillar": m.pillar, "unit": m.unit, "better": m.better,
                            "values": vals, "window_days": days})
    finally:
        c.close()
    return out


def _fmt(v: Optional[float], unit: str, detail: str) -> str:
    if v is None:
        return "—"
    num = f"{v:g}" if unit != "%" else f"{v:g} %"
    return f"{num} ({detail})" if unit in ("%", "attempts", "calls", "minutes") else num


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
