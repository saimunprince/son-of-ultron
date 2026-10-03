"""Phase 3: skills that evolve from real use, and tasks that should become skills.

Tests decide whether a skill is registered (skills.py); real use decides
whether it is good. Every call of a skill is a journal tool event, so:

- ``real_use`` counts each skill's calls and failures since its current
  version was verified, with the latest failure outputs;
- ``repairs`` turns a skill that keeps failing in real use into a limitation
  (limits.py ranks it): reproduce the failure as a new test, then a new
  version that passes old and new tests;
- ``candidates`` finds requests the human keeps making that SYRAX solves with
  the same tools, and proposes them as skills. Proposing, not building: on
  2026-10-01 the repeated-task signal was too weak to justify building, and a
  skill nobody needs is clutter.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from syrax.journal import Journal

REPAIR_MIN_USES = 3
REPAIR_MIN_RATE = 0.3
CANDIDATE_DAYS = 14
CANDIDATE_MIN_TASKS = 3
CANDIDATE_SIMILARITY = 0.5
BOOKKEEPING = {"terminate", "ask_human", "self_inspect", "know", "recall", "journal_query", "present"}


def real_use(journal: Journal, limit_events: int = 5000) -> Dict[str, dict]:
    """Per VERIFIED skill: calls and failures since its version was verified."""
    skills = {s["name"]: s for s in journal.skills(status="VERIFIED")}
    out = {n: {"uses": 0, "failures": 0, "since": s.get("last_verified") or s.get("updated") or 0, "version": s.get("version"),
               "recent_failures": []} for n, s in skills.items()}
    for e in journal.recent_events(limit_events):
        if e["type"] not in ("tool.completed", "tool.failed"):
            continue
        name = e["payload"].get("name")
        st = out.get(name)
        if st is None or e["ts"] < st["since"]:
            continue
        st["uses"] += 1
        if e["type"] == "tool.failed" or not e["payload"].get("ok", True):
            st["failures"] += 1
            if len(st["recent_failures"]) < 5:
                st["recent_failures"].append({"task_id": e.get("task_id"), "output": str(e["payload"].get("output") or "")[-300:]})
    return out


def repairs(journal: Journal) -> List[dict]:
    """Limitations for limits.rank: VERIFIED skills failing in real use."""
    out = []
    for name, st in real_use(journal).items():
        if st["uses"] < REPAIR_MIN_USES:
            continue
        rate = st["failures"] / st["uses"]
        if rate < REPAIR_MIN_RATE:
            continue
        out.append({
            "kind": "skill_repair",
            "subject": name,
            "score": round(min(1.0, rate) * 0.9, 3),
            "detail": f"skill `{name}` v{st['version']} failed {st['failures']} of {st['uses']} real uses since it was verified",
            "evidence": {"real_use": {k: st[k] for k in ("uses", "failures", "version")}, "recent_failures": st["recent_failures"]},
            "check": {"kind": "skill_verified", "name": name},
            "plan": [
                f"Read the failed `{name}` calls listed in the evidence (self_inspect with each task_id).",
                "Find the input that breaks it and why.",
                f"Write that input as a new test, keep the existing tests, and `skill_create` `{name}` again with fixed code: the new version must pass old and new tests.",
                f"Call `{name}` once for real with the input that used to fail.",
            ],
            "plan_checks": [{"kind": "tool_ok", "tools": ["self_inspect", "journal_query"]}, None,
                            {"kind": "tool_ok", "tools": ["skill_create"]}, {"kind": "tool_ok", "tools": [name]}],
        })
    return out


def _words(text: str) -> set:
    from syrax.research import keywords

    return set(keywords(text or ""))


def candidates(journal: Journal, now: Optional[float] = None) -> List[dict]:
    """Groups of similar human requests, solved with the same working tools,
    that no skill covers yet."""
    now = now or time.time()
    skills = {s["name"] for s in journal.skills()}
    rows = []
    for t in journal.tasks(limit=500):
        if t.get("kind") != "conversation" or t.get("status") != "SUCCESS" or (t.get("created") or 0) < now - CANDIDATE_DAYS * 86400:
            continue
        tools = {e["payload"].get("name") for e in journal.events(t["task_id"])
                 if e["type"] == "tool.completed" and e["payload"].get("ok")} - BOOKKEEPING - {None}
        words = _words(t.get("goal") or "")
        if tools and len(words) >= 2 and not (tools & skills):
            rows.append({"task_id": t["task_id"], "goal": t.get("goal") or "", "words": words, "tools": tools})
    groups: List[List[dict]] = []
    for r in rows:
        for g in groups:
            w = g[0]["words"]
            if len(w & r["words"]) / len(w | r["words"]) >= CANDIDATE_SIMILARITY and g[0]["tools"] & r["tools"]:
                g.append(r)
                break
        else:
            groups.append([r])
    out = []
    for g in groups:
        if len(g) < CANDIDATE_MIN_TASKS:
            continue
        common = set.intersection(*(r["words"] for r in g))
        out.append({"key": " ".join(sorted(common or g[0]["words"]))[:80], "tasks": [r["task_id"] for r in g],
                    "examples": [r["goal"][:120] for r in g[:3]], "tools": sorted(set.union(*(r["tools"] for r in g)))})
    return out


def propose_candidates(journal: Journal, now: Optional[float] = None) -> int:
    """Journal each new candidate once as a proposal for the human."""
    made = 0
    for c in candidates(journal, now):
        key = f"skill_candidate:{c['key']}"
        if journal.get_meta(key):
            continue
        journal.set_meta(key, str(now or time.time()))
        journal.record_sync("proposal.created", {
            "kind": "skill_candidate", "limitation": f"the same request came {len(c['tasks'])} times and was solved by hand each time",
            "proposal": (f"Requests like \"{c['examples'][0]}\" came {len(c['tasks'])} times in {CANDIDATE_DAYS} days and were solved with "
                         f"{', '.join(c['tools'])} each time. A skill would make it one reliable call. Say the word and SYRAX builds it."),
            "sources": [], "tasks": c["tasks"],
        })
        made += 1
    return made


def annotate(rows: List[dict], journal: Journal) -> List[dict]:
    """skills.list rows with their real-use record."""
    use = real_use(journal)
    return [{**r, "real_use": {k: v for k, v in use[r["name"]].items() if k != "recent_failures"}} if r["name"] in use else r for r in rows]
