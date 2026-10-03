"""Phase 7: a brain per kind of work, chosen from measured quality.

The human sets the brain order. Graded quality runs say how each brain does
on each kind of task (a case's prompt has a kind just like a human request),
so when one brain is clearly better at a kind - both brains have at least
MIN_GRADED graded tasks of that kind and the gap is at least MIN_GAP - it is
tried first for tasks of that kind. With less evidence the human's order
stands. Live 2026-10-03: Upstage, first after a Gemini failover, called
self_inspect twice to answer "Reply with the single word: ready".
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

from syrax.journal import Journal

KINDS = ("desktop", "research", "code", "chat", "other")
MIN_GRADED = 5
MIN_GAP = 0.15
CACHE_S = 600.0

_RULES = (
    ("desktop", re.compile(r"\b(open|launch|play|pause|volume|mute|screenshot|clipboard|battery|cpu|cores|notification|window|desktop|app)\b", re.I)),
    ("research", re.compile(r"\b(research|source|sources|cite|look up|search|find out|latest|news|who (is|was)|when (is|was)|what year|released)\b", re.I)),
    ("code", re.compile(r"\b(code|python|script|function|bug|compile|test|file|files|folder|edit|line|lines|delete|create|csv|json|\.py|\.ts|\.md|\.txt)\b", re.I)),
)


def kind_of(goal: str) -> str:
    text = goal or ""
    for kind, rx in _RULES:
        if rx.search(text):
            return kind
    return "chat" if len(text.split()) <= 12 else "other"


_cache: Dict[int, tuple] = {}


def table(journal: Journal) -> Dict[str, Dict[str, dict]]:
    """{kind: {provider: {graded, ok, quality}}} from graded quality runs.
    A task is credited to the brain that answered most of its steps."""
    hit = _cache.get(id(journal))
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    graded: Dict[str, bool] = {}
    for run in journal.quality_runs(limit=200):
        for r in run["results"]:
            if r.get("task_id"):
                graded[r["task_id"]] = bool(r.get("ok"))
    per_task = journal.answered_by()
    out: Dict[str, Dict[str, dict]] = {}
    for tid, ok in graded.items():
        provs = per_task.get(tid)
        task = journal.task(tid)
        if not provs or not task:
            continue
        main = max(provs, key=provs.get)
        st = out.setdefault(kind_of(task.get("goal") or ""), {}).setdefault(main, {"graded": 0, "ok": 0})
        st["graded"] += 1
        st["ok"] += ok
    for kinds in out.values():
        for st in kinds.values():
            st["quality"] = round((st["ok"] + 1) / (st["graded"] + 2), 2)  # Laplace, as the scorecard
    _cache[id(journal)] = (time.time(), out)
    return out


def preferred(journal: Journal, kind: str, order: List[str]) -> Optional[str]:
    """The brain to try first for this kind, or None to keep the human's order."""
    if not order:
        return None
    stats = table(journal).get(kind) or {}
    first = order[0]
    measured = [p for p in order if (stats.get(p) or {}).get("graded", 0) >= MIN_GRADED]
    if first not in measured or not measured:
        return None
    best = max(measured, key=lambda p: stats[p]["quality"])
    if best != first and stats[best]["quality"] - stats[first]["quality"] >= MIN_GAP:
        return best
    return None


def clear_cache() -> None:
    _cache.clear()
