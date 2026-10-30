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

from syrax.journal import Journal, misuse

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
        if st is None or e["ts"] < st["since"] or e["payload"].get("refused"):
            continue  # a refused call never ran: it says nothing about the skill
        if e["type"] == "tool.failed" and misuse(name, e["payload"].get("output")):
            continue  # nor does input it cannot act on (journal.misuse): a .txt given to pdf_text
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
                    "examples": [r["goal"][:120] for r in g[:3]], "tools": sorted(set.union(*(r["tools"] for r in g))),
                    "workflow": workflow_of(journal, [r["task_id"] for r in g])})
    return out


def _steps(journal: Journal, task_id: str) -> List[tuple]:
    """The successful working tool calls of a task, in order: (tool, args). A call repeated with the same arguments
    counts once."""
    started = {}
    out: List[tuple] = []
    for e in journal.events(task_id):
        p = e["payload"]
        if e["type"] == "tool.started":
            started[p.get("id")] = (p.get("name"), p.get("args") if isinstance(p.get("args"), dict) else {})
        elif e["type"] == "tool.completed" and p.get("ok") and p.get("id") in started:
            name, args = started.pop(p["id"])
            if name and name not in BOOKKEEPING and (not out or out[-1] != (name, args)):
                out.append((name, args))
    return out


def workflow_of(journal: Journal, task_ids: List[str]) -> Optional[dict]:
    """The tool sequence a group of similar requests was solved with (EVOLUTION_PLAN wave 4, directions 91 skill
    extraction, 92 workflow synthesis, 95 tool composition): the most common ordered sequence of tools, when at least
    two thirds of the tasks share it; per step, an argument equal in every task is kept and one that differs becomes a
    parameter {p1}, {p2}... A recipe for building the skill; it never runs anything itself."""
    seqs = [s for s in (_steps(journal, t) for t in task_ids) if s]
    if not seqs:
        return None
    from collections import Counter

    shape, n = Counter(tuple(name for name, _ in s) for s in seqs).most_common(1)[0]
    if n * 3 < len(seqs) * 2:
        return None
    same = [s for s in seqs if tuple(name for name, _ in s) == shape]
    steps, params = [], []
    for i, tool in enumerate(shape):
        args: Dict[str, Any] = {}
        for k in sorted(set().union(*(set(s[i][1]) for s in same))):
            values = [s[i][1].get(k) for s in same]
            if all(v == values[0] for v in values):
                args[k] = values[0]
            else:
                params.append({"name": f"p{len(params) + 1}", "step": i + 1, "arg": k, "examples": [str(v)[:40] for v in values[:3]]})
                args[k] = "{" + params[-1]["name"] + "}"
        steps.append({"tool": tool, "args": args})
    return {"steps": steps, "params": params, "support": n, "of": len(seqs)}


def render_workflow(w: Optional[dict]) -> str:
    """One line per step: `1. weather(city={p1})`."""
    if not w:
        return ""
    return " ".join(f"{i}. {s['tool']}({', '.join(f'{k}={v}' for k, v in s['args'].items())})" for i, s in enumerate(w["steps"], 1))


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
                         f"{', '.join(c['tools'])} each time. A skill would make it one reliable call. Say the word and SYRAX builds it."
                         + (f" The steps it would wrap: {render_workflow(c.get('workflow'))}" if c.get("workflow") else "")),
            "sources": [], "tasks": c["tasks"], "workflow": c.get("workflow"),
        })
        made += 1
    return made


DEPRECATE_MIN_USES, DEPRECATE_RATE, DEPRECATE_IDLE_DAYS = 5, 0.5, 60


def deprecations(journal: Journal, now: Optional[float] = None) -> List[dict]:
    """VERIFIED skills to propose for retirement (EVOLUTION_PLAN wave 4, direction 99 skill deprecation): failing at least
    DEPRECATE_RATE of at least DEPRECATE_MIN_USES real calls since this version was verified, or verified more than
    DEPRECATE_IDLE_DAYS ago and not called since. Proposing only: the human retires a skill (skill_test remove is
    refused to SYRAX's own work since 2026-10-29)."""
    now = now or time.time()
    stats = journal.tool_stats()
    out = []
    for name, st in real_use(journal).items():
        sk = journal.skill(name) or {}
        since = sk.get("last_verified") or sk.get("updated") or now
        last = (stats.get(name) or {}).get("last_used")
        if st["uses"] >= DEPRECATE_MIN_USES and st["failures"] / st["uses"] >= DEPRECATE_RATE:
            out.append({"skill": name, "version": st["version"], "why": f"failed {st['failures']} of {st['uses']} real calls since it was verified"})
        elif now - since > DEPRECATE_IDLE_DAYS * 86400 and (last is None or last < now - DEPRECATE_IDLE_DAYS * 86400):
            out.append({"skill": name, "version": st["version"], "why": f"not called in the {DEPRECATE_IDLE_DAYS} days since it was verified"})
    return out


def propose_deprecations(journal: Journal, now: Optional[float] = None) -> int:
    """Journal each deprecation once per skill version as a proposal for the human (proposal.created)."""
    made = 0
    for d in deprecations(journal, now):
        key = f"skill_deprecation:{d['skill']}:{d['version']}"
        if journal.get_meta(key):
            continue
        journal.set_meta(key, str(now or time.time()))
        journal.record_sync("proposal.created", {
            "kind": "skill_deprecation", "limitation": f"skill `{d['skill']}` {d['why']}",
            "proposal": (f"Retire skill `{d['skill']}` v{d['version']}: it {d['why']}. Removing it takes a dead option away from "
                         "the brain; skill_enable brings it back. Say the word, or keep it."),
            "sources": [], "skill": d["skill"],
        })
        made += 1
    return made


# EVOLUTION_PLAN direction 100 (skill generalization): duplicate_of refuses a new copy of a VERIFIED skill, but two
# kept skills that serve one subject stayed two tools (live 2026-10-30: youtube_open and youtube_play, both {query}).
# A pair is proposed for one general skill when the two share a name family (the word before the first "_") and the
# same argument names, or when their purposes overlap by GENERALIZE_OVERLAP or more. Proposing only: the human decides.
GENERALIZE_OVERLAP = 0.4


def generalizations(journal: Journal, root=None) -> List[dict]:
    """Pairs of VERIFIED skills, both with code under `root`, that one general skill could replace."""
    from pathlib import Path

    from syrax.skills import SKILLS_ROOT, purpose_overlap, schema_properties

    root = Path(root or SKILLS_ROOT)
    rows = []
    for r in sorted(journal.skills(status="VERIFIED"), key=lambda r: r["name"]):
        src = root / r["name"] / "skill.py"
        if src.is_file():
            rows.append((r, schema_properties(src.read_text(encoding="utf-8", errors="replace")) or set()))
    out = []
    for i, (a, pa) in enumerate(rows):
        for b, pb in rows[i + 1:]:
            fa, fb = a["name"].split("_")[0], b["name"].split("_")[0]
            overlap = purpose_overlap(a.get("purpose") or "", b.get("purpose") or "")
            if pa and pa == pb and "_" in a["name"] and "_" in b["name"] and fa == fb:
                why = f"both are `{fa}` tools taking the same arguments ({', '.join(sorted(pa))})"
            elif overlap >= GENERALIZE_OVERLAP:
                why = f"their purposes overlap {overlap:.0%}"
            else:
                continue
            out.append({"skills": [a["name"], b["name"]], "versions": [a.get("code_version"), b.get("code_version")],
                        "arguments": sorted(pa | pb), "why": why})
    return out


def propose_generalizations(journal: Journal, now: Optional[float] = None, root=None) -> int:
    """Journal each generalization once per pair of code versions as a proposal for the human (proposal.created)."""
    made = 0
    for g in generalizations(journal, root):
        a, b = g["skills"]
        key = f"skill_generalization:{a}:{b}:{g['versions'][0]}:{g['versions'][1]}"
        if journal.get_meta(key):
            continue
        journal.set_meta(key, str(now or time.time()))
        journal.record_sync("proposal.created", {
            "kind": "skill_generalization", "limitation": f"skills `{a}` and `{b}`: {g['why']}",
            "proposal": (f"Make one skill of `{a}` and `{b}`: {g['why']}. One skill taking ({', '.join(g['arguments'])}) and a "
                         "`mode` argument for what differs gives the brain one choice instead of two; the other then retires "
                         "(its code is kept). Say the word, or keep both."),
            "sources": [], "skills": [a, b],
        })
        made += 1
    return made


def annotate(rows: List[dict], journal: Journal) -> List[dict]:
    """skills.list rows with their real-use record."""
    use = real_use(journal)
    return [{**r, "real_use": {k: v for k, v in use[r["name"]].items() if k != "recent_failures"}} if r["name"] in use else r for r in rows]


# Audit 2026-10-29 (capability acquisition, "no automatic rollback"): a skill whose new version keeps failing in real
# use waited for a human's skill_rollback even when the version before it had worked. A regression is that pattern
# measured from the journal alone: the current version failed at least REPAIR_MIN_RATE of at least REPAIR_MIN_USES real
# calls since it was verified, and the newest kept version failed at most REGRESSION_PREVIOUS_RATE of at least
# REPAIR_MIN_USES real calls while it was the live one. Rolling back is reversible (the replaced code is kept).
REGRESSION_PREVIOUS_RATE = 0.15


def _use_counts(journal: Journal, name: str, start: float, end: Optional[float]) -> Dict[str, int]:
    """Real calls of `name` and their failures in [start, end): refused calls and misuse do not count (as real_use)."""
    uses = failures = 0
    for e in journal.tool_results(name, start, end):
        if e["payload"].get("refused") or (e["type"] == "tool.failed" and misuse(name, e["payload"].get("output"))):
            continue
        uses += 1
        if e["type"] == "tool.failed" or not e["payload"].get("ok", True):
            failures += 1
    return {"uses": uses, "failures": failures}


def regressions(journal: Journal, kept_versions) -> List[dict]:
    """VERIFIED skills whose current version regressed against the newest kept one (see REGRESSION_PREVIOUS_RATE).
    `kept_versions(name)` lists the code versions kept on disk, oldest first (SkillFactory.kept_versions)."""
    out = []
    for name, cur in real_use(journal).items():
        kept = kept_versions(name)
        if not kept or cur["uses"] < REPAIR_MIN_USES or cur["failures"] / cur["uses"] < REPAIR_MIN_RATE:
            continue
        prev_cv = kept[-1]
        marks = journal.skill_verifications(name)
        start = next((ts for ts, cv in marks if cv == prev_cv), None)
        if start is None:
            continue
        end = next((ts for ts, cv in marks if ts > start and cv != prev_cv), None)
        prev = _use_counts(journal, name, start, end)
        if prev["uses"] < REPAIR_MIN_USES or prev["failures"] / prev["uses"] > REGRESSION_PREVIOUS_RATE:
            continue
        out.append({"skill": name, "current": {k: cur[k] for k in ("uses", "failures", "version")},
                    "previous": {**prev, "code_version": prev_cv}, "recent_failures": cur["recent_failures"]})
    return out
