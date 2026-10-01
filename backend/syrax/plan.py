"""Phase 1: plans whose steps are checked from evidence, not from the agent's word.

An objective's plan is a list of steps (``evidence["plan"]``, text) with a
parallel list of machine checks (``evidence["plan_checks"]``, None where a
step is thinking only). A step is done when the journal shows it across the
objective's attempts: a retry resumes at the first step still unproven
instead of starting over, and an attempt that proves new steps made progress
even when the objective's final check is not met yet.

Step check kinds, all read from the events of the objective's own tasks:
  tool_ok   {"tools": [...], "min": n}  n successful calls of any listed tool
  released  {}                          a commit was created (release passed its gate)
  learned   {}                          a knowledge entry was stored
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from syrax.journal import Journal

STEP_KINDS = ("tool_ok", "released", "learned")


def steps_of(objective: dict) -> List[dict]:
    ev = objective.get("evidence") or {}
    plan = [str(s) for s in ev.get("plan") or []]
    checks = list(ev.get("plan_checks") or [])
    return [{"do": s, "check": (checks[i] if i < len(checks) and isinstance(checks[i], dict) else None)} for i, s in enumerate(plan)]


def task_ids_of(objective: dict, current: Optional[str] = None) -> List[str]:
    log = ((objective.get("progress") or {}).get("attempts_log")) or []
    ids = [a.get("task_id") for a in log] + [objective.get("last_task_id"), current]
    seen: List[str] = []
    for t in ids:
        if t and t not in seen:
            seen.append(t)
    return seen


def _met(check: dict, events: List[dict]) -> tuple[bool, Any]:
    kind = check.get("kind")
    if kind == "tool_ok":
        tools = set(check.get("tools") or [])
        want = int(check.get("min") or 1)
        n = sum(1 for e in events if e["type"] == "tool.completed" and e["payload"].get("ok") and e["payload"].get("name") in tools)
        return n >= want, {"ok_calls": n, "min": want}
    if kind == "released":
        commits = [e["payload"].get("commit") for e in events if e["type"] == "commit.created"]
        return bool(commits), {"commits": commits[:3]}
    if kind == "learned":
        ids = [e["payload"].get("knowledge_id") for e in events if e["type"] == "knowledge.stored"]
        return bool(ids), {"knowledge": ids[:5]}
    return False, {"error": f"unknown step check {kind!r}"}


def status(journal: Journal, objective: dict, task_ids: Iterable[str]) -> List[dict]:
    """Each step: done True/False from evidence, or None when it has no check
    (a thinking step counts as done once a later checked step is)."""
    events = [e for t in task_ids for e in journal.events(t)]
    out = []
    for i, st in enumerate(steps_of(objective)):
        if st["check"] is None:
            out.append({"step": i + 1, "do": st["do"], "done": None, "evidence": None})
        else:
            ok, ev = _met(st["check"], events)
            out.append({"step": i + 1, "do": st["do"], "done": ok, "evidence": ev})
    last_proven = max((s["step"] for s in out if s["done"]), default=0)
    for s in out:
        if s["done"] is None and s["step"] < last_proven:
            s["done"] = True
    return out


def next_step(steps: List[dict]) -> Optional[dict]:
    return next((s for s in steps if not s["done"]), None)


def proven(steps: List[dict]) -> int:
    return sum(1 for s in steps if s["done"])


def render(steps: List[dict]) -> str:
    if not steps:
        return ""
    nxt = next_step(steps)
    lines = []
    for s in steps:
        mark = "DONE" if s["done"] else ("NEXT" if nxt is s else "TODO")
        lines.append(f"({s['step']}) {mark}: {s['do']}")
    head = "Plan progress, proven from the journal (resume at NEXT; DONE steps need no repeating):\n"
    return head + "\n".join(lines) + "\n"


def summary(steps: List[dict]) -> Dict[str, Any]:
    nxt = next_step(steps)
    return {"proven": proven(steps), "total": len(steps), "next": nxt["step"] if nxt else None,
            "steps": [{"step": s["step"], "done": bool(s["done"])} for s in steps]}
