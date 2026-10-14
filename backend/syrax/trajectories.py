"""Phase 8 of the self-improvement plan: learning data for SYRAX's own brain.

Every finished task in the journal is a trajectory: the request, SYRAX's
thoughts with the tool calls they chose, what the tools returned, the final
answer. This module exports them as JSONL in the chat-with-tools shape most
trainers read, each with a grade the journal can vouch for (a quality case
passed or failed; an answer sent back for a false claim or a missing source),
so a later fine-tune can keep the good ones and learn from the bad ones.

Nothing leaves the machine: the file lands in backend/workspace/exports
(gitignored). A task whose text looks like a secret is skipped whole, and
repeated quality cases are capped so one prompt cannot dominate.

CLI: python -m syrax.trajectories [--since 30] [--out ...]   (docs/FINETUNE.md)
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from syrax.journal import BACKEND_ROOT, Journal

EXPORT_DIR = BACKEND_ROOT / "workspace" / "exports"
SECRET = re.compile(
    r"(?i)(password|passwd|api[_ -]?key|secret|\btoken\b|\bsk-[A-Za-z0-9]{8,}|\bgsk_[A-Za-z0-9]{8,}|\bAIza[0-9A-Za-z_-]{20,}|\bghp_[A-Za-z0-9]{20,})"
)
MAX_PER_GOAL = 3
MAX_CONTENT = 4000


def grade_of(events: List[dict], quality: Dict[str, bool]) -> str:
    """pass | fail (a quality case), sent_back (a false claim or an uncited answer), ungraded."""
    sent_back = any(e["type"] in ("claim.rejected", "claim.uncited") for e in events)
    tid = events[0]["task_id"] if events else None
    if tid in quality:
        return ("pass" if quality[tid] else "fail") if not sent_back else "fail"
    return "sent_back" if sent_back else "ungraded"


def messages_of(task: dict, events: List[dict]) -> List[dict]:
    """The task as chat messages: user request, assistant thoughts with tool_calls, tool results, the final."""
    msgs: List[dict] = [{"role": "user", "content": str(task.get("goal") or "")[:MAX_CONTENT]}]
    for e in events:
        t, p = e["type"], e["payload"]
        if t == "think":
            calls = [{"id": str(c.get("id") or ""), "name": str(c.get("name") or ""), "arguments": c.get("args") if isinstance(c.get("args"), dict) else {}}
                     for c in (p.get("tools") or []) if c.get("name") and c.get("name") != "terminate"]
            content = str(p.get("content") or "")[:MAX_CONTENT]
            if calls or content:
                m: Dict[str, Any] = {"role": "assistant", "content": content}
                if calls:
                    m["tool_calls"] = calls
                msgs.append(m)
        elif t in ("tool.completed", "tool.failed"):
            if p.get("name") == "terminate":
                continue
            msgs.append({"role": "tool", "tool_call_id": str(p.get("id") or ""), "name": str(p.get("name") or ""),
                         "content": str(p.get("output") or "")[:MAX_CONTENT], "ok": bool(p.get("ok")) and t == "tool.completed",
                         **({"refused": True} if p.get("refused") else {})})
        elif t == "ask":
            msgs.append({"role": "assistant", "content": str(p.get("question") or "")[:MAX_CONTENT]})
        elif t == "answer":
            msgs.append({"role": "user", "content": str(p.get("text") or "")[:MAX_CONTENT]})
    final = str(task.get("result") or "")
    if final and not (msgs[-1]["role"] == "assistant" and msgs[-1]["content"] == final and "tool_calls" not in msgs[-1]):
        msgs.append({"role": "assistant", "content": final[:MAX_CONTENT]})
    return msgs


def looks_secret(msgs: Iterable[dict]) -> bool:
    return any(SECRET.search(json.dumps(m, ensure_ascii=False)) for m in msgs)


def quality_grades(journal: Journal) -> Dict[str, bool]:
    out: Dict[str, bool] = {}
    for run in journal.quality_runs(limit=500):
        for r in run.get("results") or []:
            if r.get("task_id"):
                out[str(r["task_id"])] = bool(r.get("ok"))
    return out


def trajectories(journal: Journal, since: float = 0.0, kinds: Iterable[str] = ("conversation", "eval", "autonomous"),
                 max_per_goal: int = MAX_PER_GOAL) -> Dict[str, Any]:
    """{"rows": [...], "counts": {...}}: finished tasks since `since`, graded, deduplicated, secrets skipped."""
    kinds = set(kinds)
    grades = quality_grades(journal)
    rows, counts, per_goal = [], Counter(), Counter()
    for task in journal.tasks(limit=500, status=("SUCCESS", "PARTIAL")):
        if task.get("created", 0) < since or task.get("kind") not in kinds:
            continue
        events = journal.events(task["task_id"], limit=2000)
        if not any(e["type"] == "final" for e in events):
            counts["no_final"] += 1
            continue
        msgs = messages_of(task, events)
        if looks_secret(msgs):
            counts["skipped_secret"] += 1
            continue
        key = str(task.get("goal") or "")[:200]
        if per_goal[key] >= max_per_goal:
            counts["deduped"] += 1
            continue
        per_goal[key] += 1
        grade = grade_of(events, grades)
        counts[grade] += 1
        rows.append({"task_id": task["task_id"], "kind": task.get("kind"), "status": task.get("status"), "created": task.get("created"),
                     "grade": grade, "tools": [m["name"] for m in msgs if m["role"] == "tool"], "messages": msgs})
    counts["exported"] = len(rows)
    return {"rows": rows, "counts": dict(counts)}


def export(journal: Journal, out: Optional[Path] = None, since_days: float = 30.0, kinds: Iterable[str] = ("conversation", "eval", "autonomous"),
           now: Optional[float] = None) -> Dict[str, Any]:
    now = now or time.time()
    data = trajectories(journal, since=now - since_days * 86400, kinds=kinds)
    out = out or (EXPORT_DIR / f"trajectories-{time.strftime('%Y%m%d', time.localtime(now))}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for row in data["rows"]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"out": str(out), **data["counts"]}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Export SYRAX's task trajectories as JSONL for fine-tuning (docs/FINETUNE.md)")
    ap.add_argument("--journal", default=str(BACKEND_ROOT / "config" / "journal.db"))
    ap.add_argument("--since", type=float, default=30.0, help="days back (default 30)")
    ap.add_argument("--kinds", default="conversation,eval,autonomous")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    j = Journal(Path(a.journal), recover=False)
    try:
        rep = export(j, Path(a.out) if a.out else None, a.since, [k for k in a.kinds.split(",") if k])
    finally:
        j.close()
    print(json.dumps(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
