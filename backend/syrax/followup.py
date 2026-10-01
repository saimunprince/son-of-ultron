"""Phase 1: the next objective comes from what the last one taught.

When an objective is BLOCKED, the journal says why, and that decides what
comes next instead of the objective simply waiting for a human:

- it released a change and the check still failed → a follow-up objective
  with the same check, told which commits did not do it and which failures
  happened after them (the fix missed a cause; find the next one);
- it neither released nor learned anything → it did not know how. First a
  learning objective (research, learn one verified conclusion), then a retry
  of the original that depends on it and is briefed with what was learned.

Follow-ups of follow-ups stop at MAX_DEPTH, and each blocked objective gets
its follow-ups once (idempotent keys).
"""

from __future__ import annotations

from typing import Any, Dict, List

from syrax import plan
from syrax.journal import Journal

MAX_DEPTH = 2
KEEP = ("limitation", "plan", "plan_checks")


def derive(journal: Journal, objective: dict) -> List[dict]:
    """Objectives created from a just-BLOCKED objective (re-read after the block)."""
    ev = objective.get("evidence") or {}
    spec = objective.get("check_spec") or {}
    depth = int(ev.get("followup_depth") or 0)
    if depth >= MAX_DEPTH or spec.get("kind") in ("human", None):
        return []
    oid = objective["id"]
    events = [e for t in plan.task_ids_of(objective) for e in journal.events(t)]
    commits = [e for e in events if e["type"] == "commit.created"]
    learned = [e for e in events if e["type"] == "knowledge.stored"]
    log = ((objective.get("progress") or {}).get("attempts_log")) or []
    lessons = [str(a.get("lesson") or "")[:200] for a in log[-3:]]
    base: Dict[str, Any] = {k: ev[k] for k in KEEP if ev.get(k)}
    base.update({"followup_of": oid, "followup_depth": depth + 1, "lessons": lessons})
    goal = str(objective.get("goal") or "")
    first_step = (ev.get("plan") or [None])[0]
    out: List[dict] = []
    if commits:
        shas = [str(c["payload"].get("commit") or "")[:7] for c in commits][-3:]
        after = commits[-1]["ts"]
        tool = spec.get("tool")
        failures = [
            {"task_id": e.get("task_id"), "output": str(e["payload"].get("output") or "")[-240:]}
            for e in journal.events_between(after, limit=5000)
            if tool and e["type"] == "tool.failed" and e["payload"].get("name") == tool
        ][-5:]
        o = journal.add_objective_sync(
            goal=f"My change {', '.join(shas)} for objective #{oid} did not meet its check. Find the cause it missed and fix that. "
                 f"The original objective: {goal[:400]}",
            reason=f"follow-up of #{oid}: released, but the check still failed",
            priority=objective.get("priority") or 3, source="followup", check=spec, key=f"followup:{oid}:released",
            evidence={**base, "released": shas, "failures_after_release": failures},
            next_action="read the failures after the release" + (f", then: {first_step}" if first_step else ""),
        )
        if o:
            out.append(o)
    elif not learned:
        limitation = (ev.get("limitation") or {}).get("detail")
        topic = str(limitation or goal)[:120]
        learn = journal.add_objective_sync(
            goal=f"Learn how to do what objective #{oid} could not: {topic}. `research` it and `learn` one verified conclusion with sources.",
            reason=f"follow-up of #{oid}: blocked without a release or anything learned",
            priority=objective.get("priority") or 3, source="followup", check={"kind": "knowledge_stored", "topic": topic},
            key=f"followup:{oid}:learn",
            evidence={"followup_of": oid, "followup_depth": depth + 1, "lessons": lessons,
                      "plan": [f"`research` how to: {topic}.", "`learn` one verified conclusion with its sources."],
                      "plan_checks": [{"kind": "tool_ok", "tools": ["research"]}, {"kind": "learned"}]},
            next_action=f"`research` how to: {topic}",
        )
        if learn:
            out.append(learn)
            retry = journal.add_objective_sync(
                goal=goal, reason=f"retry of #{oid} once #{learn['id']} has learned how",
                priority=objective.get("priority") or 3, source="followup", check=spec, key=f"followup:{oid}:retry",
                dependencies=[learn["id"]], evidence={**base, "learn_first": learn["id"]},
                next_action=first_step or "apply what was learned",
            )
            if retry:
                out.append(retry)
    if out:
        journal.record_sync("followup.derived", {"objective_id": oid, "created": [o["id"] for o in out],
                                                  "why": "released, check still failed" if commits else "blocked without knowing how"})
    return out


def learned_brief(journal: Journal, objective: dict, budget: int = 900) -> str:
    """For a retry: what its learning objective stored, so the attempt uses it."""
    rid = (objective.get("evidence") or {}).get("learn_first")
    if not rid:
        return ""
    r = journal.objective(int(rid)) or {}
    ids = (((r.get("evidence") or {}).get("judged")) or {}).get("matching") or []
    rows = [k for k in (journal.knowledge(int(i)) for i in ids[:3]) if k]
    if not rows:
        return ""
    lines = [f"- #{k['id']} ({k['confidence']:.0%}): {str(k['claim'])[:260]}" + (f" [{k['source_url']}]" if k.get("source_url") else "") for k in rows]
    return (f"What objective #{rid} learned for this (use it):\n" + "\n".join(lines))[:budget] + "\n"

