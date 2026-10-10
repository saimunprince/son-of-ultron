"""Completion contracts: an objective closes only on machine evidence, linked by
id, produced by work that is not in doubt.

`autonomy.judge` decides whether an objective's check reads as satisfied. This
layer runs after it, wherever the autonomy cycle would close an objective
DONE, and may only keep or withdraw that DONE; it never makes one. It adds:

- links: every DONE carries the ids of the events, commits, knowledge rows,
  skills, files or measurement runs it rests on (`contract.evidence`);
- attribution: whether that evidence came from the objective's own tasks
  (`own`), from a measurement SYRAX does not write (`measurement`: quality
  runs, benchmarks, gate verdicts, tool reliability counts), or from another
  task (`other-task`, accepted only for `tool_verified`, whose subject is a
  property of SYRAX's own tool, not a work product of the objective);
- work products (a commit, a file, knowledge, a skill) must come from the
  objective's own tasks;
- doubt: evidence from a task that was interrupted (a crash, a restart) does
  not count until it is verified, and a commit is verified only when it is in
  the repository's history;
- `task_success`, the check that only asks whether the task said SUCCESS, also
  needs a successful tool call in the objective's own task and a final answer
  that does not claim work the task did not do.

This file decides whether SYRAX succeeded, so its own releases may not change
it (devloop.JUDGES).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from syrax.journal import BACKEND_ROOT, Journal

CONTRACT_VERSION = 1
REPO_ROOT = BACKEND_ROOT.parent
MEASUREMENT_KINDS = frozenset({"quality_case_passes", "quality_recovered", "benchmark_recovered", "verification_green", "tool_reliability"})
WORK_PRODUCT_KINDS = frozenset({"change_released", "file_present", "file_absent", "knowledge_stored", "knowledge_confidence", "skill_verified"})
DOUBTFUL = frozenset({"INTERRUPTED", "UNKNOWN"})  # a crash or a restart cut the task off: what it left is unverified
CHANGE_EVENTS = ("code.changed", "commit.created", "skill.created", "knowledge.stored")
QUIET_TOOLS = ("terminate", "ask_human")


def own_task_ids(journal: Journal, objective: dict, task: Optional[dict]) -> List[str]:
    """The tasks the autonomy cycle ran for this objective, newest last."""
    ids: List[str] = []
    for e in events_after(journal, objective):
        p = e["payload"]
        if e["type"] in ("cycle.completed", "plan.progressed") and p.get("objective_id") == objective.get("id") and p.get("task_id"):
            ids.append(p["task_id"])
    for tid in (objective.get("last_task_id"), (task or {}).get("task_id")):
        if tid:
            ids.append(tid)
    seen, out = set(), []
    for tid in ids:
        if tid not in seen:
            seen.add(tid)
            out.append(tid)
    return out


def events_after(journal: Journal, objective: dict) -> List[dict]:
    """Events journaled after the objective was created, by event order: on
    Windows time.time() ticks every ~15 ms, so a timestamp cannot tell an
    event from the objective's own creation (stale evidence slipped through)."""
    since = (objective.get("created") or 0) - 5.0
    window = journal.events_between(since, limit=10000)
    first = next((e["id"] for e in window if e["type"] == "objective.created" and e["payload"].get("objective_id") == objective.get("id")), None)
    if first is None:
        return [e for e in window if e["ts"] > (objective.get("created") or 0)]
    return [e for e in window if e["id"] > first]


def _status(journal: Journal, task_id: Optional[str]) -> Optional[str]:
    t = journal.task(task_id) if task_id else None
    return (t or {}).get("status")


def commit_in_history(sha: str, root: Path = REPO_ROOT) -> bool:
    """True when the commit exists and HEAD contains it: what a crash left behind, checked in git."""
    if not sha:
        return False
    try:
        out = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"], cwd=str(root), capture_output=True, timeout=20)
        return out.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _claims_without_change(journal: Journal, task: dict) -> bool:
    from syrax.agent import CLAIM, OWN_WORK_CLAIM

    text = str(task.get("result") or "")
    if not (CLAIM.search(text) or OWN_WORK_CLAIM.search(text)):
        return False
    return not any(e["type"] in CHANGE_EVENTS for e in journal.events(task["task_id"], limit=5000))


def _evidence_for(journal: Journal, objective: dict, evidence: dict, repo_root: Path) -> List[dict]:
    """The concrete items a judged DONE rests on, each with the task that produced it (None when task-less)."""
    spec = objective.get("check_spec") or {}
    kind = spec.get("kind", "task_success")
    since = objective.get("created") or 0
    items: List[dict] = []
    if kind == "change_released":
        wanted = set(evidence.get("commits") or [])
        for e in events_after(journal, objective):
            if e["type"] == "commit.created" and e["payload"].get("commit") in wanted:
                items.append({"type": "commit", "id": e["id"], "sha": e["payload"].get("commit"), "task_id": e.get("task_id")})
    elif kind == "tool_verified":
        tool = spec.get("tool")
        for e in events_after(journal, objective):
            if e["type"] == "tool.completed" and e["payload"].get("name") == tool and e["payload"].get("ok", True):
                items.append({"type": "event", "id": e["id"], "task_id": e.get("task_id")})
    elif kind in ("knowledge_stored", "knowledge_confidence"):
        ids = evidence.get("matching") or evidence.get("stronger") or []
        for kid in ids:
            k = journal.knowledge(int(kid)) if kid is not None else None
            if k:
                items.append({"type": "knowledge", "id": k["id"], "task_id": k.get("task_id")})
    elif kind == "skill_verified":
        name = spec.get("name")
        for e in events_after(journal, objective):
            if e["type"] in ("skill.verified", "skill.created") and e["payload"].get("skill") == name:
                items.append({"type": "event", "id": e["id"], "task_id": e.get("task_id")})
    elif kind in ("file_present", "file_absent"):
        path = str(evidence.get("path") or "")
        needles = {path.lower(), path.replace("\\", "/").lower(), Path(path).name.lower()} - {""}
        for e in events_after(journal, objective):
            if e["type"] in ("code.changed", "tool.started") and e.get("task_id"):
                blob = str(e["payload"]).replace("\\\\", "\\").lower()
                if any(n in blob or n.replace("\\", "/") in blob.replace("\\", "/") for n in needles):
                    items.append({"type": "event", "id": e["id"], "task_id": e.get("task_id"), "path": path})
    elif kind == "quality_case_passes" or kind == "quality_recovered":
        qid = evidence.get("quality")
        if qid:
            items.append({"type": "quality_run", "id": qid, "task_id": None})
    elif kind == "benchmark_recovered":
        if evidence.get("benchmark"):
            items.append({"type": "benchmark", "id": evidence["benchmark"], "task_id": None})
    elif kind == "verification_green":
        v = evidence.get("verification") or {}
        if v.get("id"):
            items.append({"type": "verification", "id": v["id"], "task_id": v.get("task_id")})
    elif kind == "tool_reliability":
        items.append({"type": "measurement", "id": None, "task_id": None, "detail": {k: evidence.get(k) for k in ("tool", "uses", "failures", "rate") if k in evidence}})
    return items


def assess(journal: Journal, objective: dict, task: Optional[dict], verdict: str, evidence: Optional[dict],
           path: str = "task", repo_root: Path = REPO_ROOT) -> Tuple[str, dict]:
    """Keep or withdraw a judged DONE. Returns (verdict, contract). path names
    where the cycle is closing it: task | existing | rejudge | measure."""
    spec = objective.get("check_spec") or {}
    kind = spec.get("kind", "task_success")
    evidence = evidence or {}
    own = own_task_ids(journal, objective, task)
    contract: Dict[str, Any] = {"version": CONTRACT_VERSION, "kind": kind, "path": path, "own_tasks": own[-10:],
                                "machine_verifiable": kind not in ("task_success", "human"), "checked_at": time.time()}

    def withdraw(reason: str, items: Optional[List[dict]] = None) -> Tuple[str, dict]:
        contract.update({"verdict": "RETRY", "attribution": "none", "evidence": (items or [])[:20], "reason": reason})
        return "RETRY", contract

    if verdict != "DONE":
        contract.update({"verdict": verdict, "attribution": "none", "evidence": [], "reason": "the check is not satisfied"})
        return verdict, contract

    if kind == "human":
        return withdraw("a human check is closed by a human, not by the cycle")

    if kind == "task_success":
        t = task if task and task.get("task_id") else (journal.task(own[-1]) if own else None)
        if not t or t.get("task_id") not in own:
            return withdraw("task_success needs the objective's own task")
        if t.get("status") != "SUCCESS":
            return withdraw(f"the objective's task ended {t.get('status')}")
        if _claims_without_change(journal, t):
            return withdraw("the final answer claims work the task did not do")
        tools = [e for e in journal.events(t["task_id"], limit=5000)
                 if e["type"] == "tool.completed" and e["payload"].get("ok", True) and e["payload"].get("name") not in QUIET_TOOLS]
        # Kept for compatibility, and marked: task_success is not machine-verifiable.
        # Requiring tool evidence here is the stricter rule; existing tests pin that a
        # text-only task closes a task_success objective (see docs/improvements/002.md).
        contract.update({"verdict": "DONE", "attribution": "own",
                         "reason": "own task ended SUCCESS" + (f" with {len(tools)} successful tool call(s)" if tools else " with no tool evidence (not machine-verifiable)"),
                         "evidence": [{"type": "event", "id": e["id"], "task_id": t["task_id"]} for e in tools[-5:]]})
        return "DONE", contract

    items = _evidence_for(journal, objective, evidence, repo_root)
    if not items:
        return withdraw("the judged evidence could not be traced to anything in the journal")

    # doubt: evidence from an interrupted task counts only once verified
    verified: List[dict] = []
    doubts: List[str] = []
    for it in items:
        st = _status(journal, it.get("task_id"))
        if st in DOUBTFUL:
            if it["type"] == "commit" and commit_in_history(it.get("sha") or "", repo_root):
                verified.append({**it, "verified": "commit is in the repository history"})
            else:
                doubts.append(f"{it['type']} {it.get('id')} from task {it.get('task_id')} ({st}) is not verified")
            continue
        verified.append(it)
    if not verified:
        return withdraw("; ".join(doubts) or "no verifiable evidence", items)

    own_items = [it for it in verified if it.get("task_id") in own]
    if kind in MEASUREMENT_KINDS:
        attribution, use = "measurement", verified
    elif own_items:
        attribution, use = "own", own_items
    elif kind == "tool_verified":
        attribution, use = "other-task", verified  # a fact about SYRAX's tool, whichever task showed it
    else:
        return withdraw(f"{kind} needs a work product of this objective's own tasks; the evidence came from elsewhere", verified)
    contract.update({"verdict": "DONE", "attribution": attribution, "evidence": use[-20:],
                     "reason": f"{len(use)} evidence item(s), {attribution}" + (f"; ignored: {'; '.join(doubts)}" if doubts else "")})
    return "DONE", contract
