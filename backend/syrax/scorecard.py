"""Phase 7, first step: what each brain is actually good at, from the journal.

A task is credited to the brain that answered most of its steps. Per brain:
tasks, success rate, average steps, and — where quality runs graded the task —
quality (Laplace-smoothed so 2 of 2 does not beat 69 of 80). There is not yet
enough variety of task kinds to route by kind; what the evidence can already
say is whether the human's brain order matches measured quality.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

from syrax.journal import Journal

MIN_GRADED = 10       # graded tasks a brain needs before its quality is compared
MIN_GAP = 0.15        # smoothed quality difference that is worth a proposal


def compute(journal: Journal) -> Dict[str, dict]:
    per_task = journal.answered_by()
    graded: Dict[str, bool] = {}
    for run in journal.quality_runs(limit=200):
        for r in run["results"]:
            if r.get("task_id"):
                graded[r["task_id"]] = bool(r.get("ok"))
    out: Dict[str, dict] = defaultdict(lambda: {"tasks": 0, "success": 0, "steps": 0, "graded": 0, "graded_ok": 0})
    for tid, provs in per_task.items():
        task = journal.task(tid)
        if not task or not provs:
            continue
        main = max(provs, key=provs.get)
        s = out[main]
        s["tasks"] += 1
        s["success"] += task.get("status") == "SUCCESS"
        s["steps"] += task.get("current_step") or 0
        if tid in graded:
            s["graded"] += 1
            s["graded_ok"] += graded[tid]
    result = {}
    for pid, s in out.items():
        if not pid:
            continue
        result[pid] = {
            "tasks": s["tasks"],
            "success_rate": round(s["success"] / s["tasks"], 2) if s["tasks"] else None,
            "avg_steps": round(s["steps"] / s["tasks"], 1) if s["tasks"] else None,
            "graded": s["graded"],
            "quality": round((s["graded_ok"] + 1) / (s["graded"] + 2), 2),
        }
    return result


def order_proposal(card: Dict[str, dict], order: List[str]) -> Optional[dict]:
    """A brain placed above a clearly better-measured one, both with enough graded tasks."""
    ranked = [p for p in order if p in card and card[p]["graded"] >= MIN_GRADED]
    for i, upper in enumerate(ranked):
        for lower in ranked[i + 1:]:
            gap = card[lower]["quality"] - card[upper]["quality"]
            if gap >= MIN_GAP:
                return {
                    "kind": "brain_order",
                    "limitation": f"{upper} is tried before {lower} but does worse on graded tasks",
                    "proposal": (f"Measured task quality: {lower} {card[lower]['quality']:.0%} over {card[lower]['graded']} graded tasks, "
                                 f"{upper} {card[upper]['quality']:.0%} over {card[upper]['graded']}. Moving {lower} above {upper} in BRAIN "
                                 f"should raise answer quality."),
                    "sources": [],
                }
    return None


def render(card: Dict[str, dict]) -> str:
    rows = sorted(card.items(), key=lambda x: -x[1]["tasks"])
    return "\n".join(
        f"{p}: {c['tasks']} tasks, success {c['success_rate']:.0%}, {c['avg_steps']} steps avg, "
        f"quality {c['quality']:.0%} over {c['graded']} graded" for p, c in rows
    ) or "no brain has answered a task yet"


def daily_proposal(journal: Journal, order: List[str]) -> Optional[dict]:
    """Journal an order proposal at most once per distinct finding."""
    prop = order_proposal(compute(journal), order)
    if not prop:
        return None
    key = "scorecard_last_proposal"
    if journal.get_meta(key) == prop["limitation"]:
        return None
    journal.set_meta(key, prop["limitation"])
    journal.record_sync("proposal.created", prop)
    return prop
