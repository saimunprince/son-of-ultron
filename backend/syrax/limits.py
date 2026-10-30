"""Phase 1 — "what is my biggest limitation right now?"

When nothing is failing loudly enough to derive an objective, SYRAX used to go
IDLE ("no open objective"). Instead it now ranks its limitations from journal
evidence, takes the strongest one, and turns it into an objective with a plan
and a measurable check. The ranking itself is journaled (`limitation.ranked`),
so the WHY view shows what was considered and why one was chosen.

Scores are impact x confidence in 0..1, computed from counts, never from the
model's opinion:

  tool reliability   failure rate x volume weight, for tools used 5+ times
                     with at least 15 % failures
  brain availability failover share of recent brain calls (24 h)
  known limitation   a fixed low score: written in docs/system_map.json,
                     worth researching when nothing measured is worse

Each limitation is offered at most once per ISO week (objective key), so a
DONE or BLOCKED one is not chased again immediately.
"""

from __future__ import annotations

import datetime
import math
import time
from typing import Any, Callable, Dict, List, Optional

from syrax.journal import ALL_OBJECTIVES, Journal

MIN_USES = 5
RECENT_USES = 40  # judge a tool on its latest uses: a fixed problem must stop ranking high
MIN_FAIL_RATE = 0.15
BRAIN_WINDOW_S = 86400.0
MIN_BRAIN_CALLS = 10
MIN_FAILOVER_SHARE = 0.3
KNOWN_LIMITATION_SCORE = 0.15
KNOWN_PER_DAY = 3  # research-only objectives from the system map; measured limitations are not capped
SKIP_TOOLS = {"terminate", "ask_human"}


def _week(ts: Optional[float] = None) -> str:
    y, w, _ = datetime.date.fromtimestamp(ts or time.time()).isocalendar()
    return f"{y}-W{w:02d}"


def tool_failures(journal: Journal, tool: str, limit: int = 5) -> List[dict]:
    rows = []
    for e in reversed(journal.recent_events(1000)):
        if e["type"] == "tool.failed" and e["payload"].get("name") == tool:
            rows.append({"task_id": e.get("task_id"), "output": str(e["payload"].get("output") or "")[-300:]})
            if len(rows) >= limit:
                break
    return rows


def refused(payload: dict) -> bool:
    """A call a guard turned down never ran as the tool: the permission gate, or `release`
    refusing its plan. Events journaled before the flag existed (0c77fab) carry only the
    words, so the ranking reads those too; without that, 13 old refusals kept `release`
    ranked first as a broken tool (2026-10-12)."""
    if payload.get("refused"):
        return True
    return payload.get("name") == "release" and "Error: release refused:" in str(payload.get("output") or "")


def probe_tasks(journal: Journal) -> Callable[[Optional[str]], bool]:
    """A test for "was this use a quality case": tasks of kind `eval` are left out of a tool's reliability.
    Some fail the tool on purpose (self_patch_stale applies a stale diff and must report it), and a case the
    brain fails is a quality failure that the repro hunts take. Live 2026-10-26: `apply_patch` ranked first
    with 18 of its last 40 uses failing, 8 of them quality cases (the stale probe, a diff of a file the brain
    never read); without them 10 of 40. Task kinds are looked up once per task."""
    kinds: Dict[str, Optional[str]] = {}

    def is_probe(task_id: Optional[str]) -> bool:
        if not task_id:
            return False
        if task_id not in kinds:
            row = journal.task(task_id)
            kinds[task_id] = row.get("kind") if row else None
        return kinds[task_id] == "eval"

    return is_probe


def recent_tool_stats(journal: Journal, per_tool: int = RECENT_USES) -> Dict[str, dict]:
    """successes/failures over each tool's latest ``per_tool`` outcomes.
    Live: str_replace_editor was 5 % in the last 4 h after its fix but still
    ranked first on its all-time 20 %."""
    outcomes: Dict[str, List[bool]] = {}
    is_probe = probe_tasks(journal)
    for e in reversed(journal.recent_events(5000)):
        if e["type"] not in ("tool.completed", "tool.failed"):
            continue
        if refused(e["payload"]):
            continue  # a call a guard refused never ran as the tool; it is not the tool failing
        if is_probe(e.get("task_id")):
            continue  # a quality case measures the brain, not the tool
        name = e["payload"].get("name")
        lst = outcomes.setdefault(name, [])
        if len(lst) < per_tool:
            lst.append(e["type"] == "tool.completed")
    return {n: {"successes": sum(v), "failures": len(v) - sum(v), "window": per_tool} for n, v in outcomes.items() if n}


def rank(journal: Journal, selfmodel: Any, now: Optional[float] = None) -> List[dict]:
    """Every measurable limitation, strongest first."""
    now = now or time.time()
    out: List[dict] = []
    from syrax import skillevo

    skill_names = {s["name"] for s in journal.skills()}
    for tool, st in recent_tool_stats(journal).items():
        done = st["successes"] + st["failures"]
        if tool in SKIP_TOOLS or tool in skill_names or done < MIN_USES:  # skills are repaired as skills (below)
            continue
        rate = st["failures"] / done
        if rate < MIN_FAIL_RATE:
            continue
        volume = min(1.0, math.log(done + 1) / math.log(41))  # 40 uses → full weight
        target = round(max(0.05, rate / 2), 2)
        out.append({
            "kind": "tool_reliability",
            "subject": tool,
            "score": round(rate * volume, 3),
            "detail": f"`{tool}` failed {st['failures']} of its last {done} uses ({rate:.0%})",
            "evidence": {"stats": st, "recent_failures": tool_failures(journal, tool)},
            "check": {"kind": "tool_reliability", "tool": tool, "max_rate": target, "min_uses": MIN_USES},
            "plan": [
                f"Read the recent `{tool}` failures listed in the evidence (self_inspect with each task_id).",
                "Group them by cause; pick the cause behind most failures.",
                "Fix that cause in SYRAX's own code or prompts (never in tests or in the files that judge you), add a new test, and `release`.",
                f"Then use `{tool}` {MIN_USES} times with harmless, realistic calls inside the workspace so the new failure rate is measured (target ≤ {target:.0%}).",
            ],
            "plan_checks": [{"kind": "tool_ok", "tools": ["self_inspect", "journal_query"]}, None, {"kind": "released"}, {"kind": "tool_ok", "tools": [tool], "min": MIN_USES}],
        })
    out += skillevo.repairs(journal)  # Phase 3: a skill failing in real use gets a new version
    answered = failed = 0
    for e in journal.events_between(now - BRAIN_WINDOW_S, now, limit=10000):
        if e["type"] == "brain.answered":
            answered += 1
        elif e["type"] == "brain.failover":
            failed += 1
    calls = answered + failed
    if calls >= MIN_BRAIN_CALLS and failed / calls >= MIN_FAILOVER_SHARE:
        share = failed / calls
        out.append({
            "kind": "brain_availability",
            "subject": "brains",
            "score": round(share * 0.8, 3),
            "detail": f"{failed} of {calls} brain calls in the last 24 h failed over ({share:.0%})",
            "evidence": {"answered": answered, "failovers": failed},
            "check": {"kind": "knowledge_stored", "topic": "free LLM API rate limits tool calling providers"},
            "plan": [
                "Read the failover reasons in the journal (self_inspect summary and recent tasks).",
                "`research` which free or cheap LLM APIs support tool calling and what their rate limits are.",
                "`learn` one verified conclusion with sources: which provider order or model choice would cut failovers.",
                "Report the proposal; changing keys or providers is the human's decision.",
            ],
            "plan_checks": [{"kind": "tool_ok", "tools": ["self_inspect", "journal_query"]}, {"kind": "tool_ok", "tools": ["research"]}, {"kind": "learned"}, None],
        })
    try:
        weaknesses = selfmodel.weaknesses()
    except Exception:
        weaknesses = []
    since = now - 86400
    known_today = sum(1 for o in journal.objectives_since(since)
                      if (o.get("key") or "").startswith("limit:known_limitation:"))
    for w in weaknesses:
        if w.get("kind") != "known_limitation" or known_today >= KNOWN_PER_DAY:
            continue
        out.append({
            "kind": "known_limitation",
            "subject": w["detail"][:80],
            "score": KNOWN_LIMITATION_SCORE,
            "detail": w["detail"],
            "evidence": {"source": w.get("evidence")},
            "check": {"kind": "knowledge_stored", "topic": w["detail"][:80]},
            "plan": [
                f"`research` how comparable systems overcome: {w['detail']}.",
                "`learn` one verified conclusion with sources.",
                "Say what change to SYRAX it suggests and what it would cost; build nothing yet.",
            ],
            "plan_checks": [{"kind": "tool_ok", "tools": ["research"]}, {"kind": "learned"}, None],
        })
    stats = kind_stats(journal)
    tried = sum(st["total"] for st in stats.values())
    for x in out:
        st = stats.get(x["kind"], {"done": 0, "total": 0, "calls": None})
        x["confidence"], x["explore_bonus"], x["cost"], x["value"] = value_of(x["score"], st, tried)
    out.sort(key=lambda x: (-x["value"], -x["score"]))
    return out


def value_of(score: float, st: dict, tried: int) -> tuple:
    """(confidence, explore_bonus, cost, value) of a limitation whose kind has stats `st`, `tried` attempts over all
    kinds. Confidence is Laplace (a new kind starts at 0.5). EVOLUTION_PLAN wave 4 (directions 184, 185, 187, 188): an
    exploration bonus (UCB) for kinds tried rarely, so the ranking does not keep choosing the kinds it already knows;
    it shrinks as a kind gathers attempts."""
    confidence = round((st["done"] + 1) / (st["total"] + 2), 2)
    bonus = round(EXPLORE_C * math.sqrt(math.log(tried + 1) / (st["total"] + 1)), 3)
    cost = st["calls"] if st.get("calls") is not None else DEFAULT_COST
    return confidence, bonus, cost, round(score * min(1.0, confidence + bonus) / (1 + cost / 20), 4)


DEFAULT_COST = 10.0  # brain calls, until a kind has history
EXPLORE_C = 0.3  # weight of the exploration bonus: optimistic success = confidence + C * sqrt(ln N / (n + 1)), at most 1


def kind_stats(journal: Journal) -> Dict[str, dict]:
    """Per limitation kind: how many objectives closed DONE out of those that
    ended (DONE/BLOCKED/DROPPED), and the average brain calls they spent."""
    out: Dict[str, dict] = {}
    for o in journal.objectives(limit=ALL_OBJECTIVES, status=["DONE", "BLOCKED", "DROPPED"]):
        kind = (((o.get("evidence") or {}).get("limitation")) or {}).get("kind")
        if not kind:
            continue
        st = out.setdefault(kind, {"done": 0, "total": 0, "calls_sum": 0, "calls_n": 0})
        st["total"] += 1
        st["done"] += o["status"] == "DONE"
        tasks = {a.get("task_id") for a in ((o.get("progress") or {}).get("attempts_log") or [])} | {o.get("last_task_id")}
        calls = sum(1 for t in tasks if t for e in journal.events(t) if e["type"] == "brain.answered")
        if calls:
            st["calls_sum"] += calls
            st["calls_n"] += 1
    return {k: {"done": v["done"], "total": v["total"], "calls": round(v["calls_sum"] / v["calls_n"], 1) if v["calls_n"] else None}
            for k, v in out.items()}


RESEARCHED_FOR_S = 90 * 86400.0


def researched_subjects(journal: Journal, now: Optional[float] = None) -> set:
    """Known limitations a DONE objective already researched in the last RESEARCHED_FOR_S."""
    since = (now or time.time()) - RESEARCHED_FOR_S
    return {((o.get("evidence") or {}).get("limitation") or {}).get("subject")
            for o in journal.objectives_since(since, limit=2000)
            if o.get("status") == "DONE" and str(o.get("key") or "").startswith("limit:known_limitation:")} - {None}


# A reworded subject is still the subject already researched. Live 2026-10: objective 311 repeated 268 (the
# 80-character keys differ only at character 79; word similarity 1.0) and 310 repeated 303 ("Core: one task at
# a time; no queue scheduling" became "Core: one task runs at a time; a human request made meanwhile is queued
# (PENDING"): word similarity 0.31, but 3 of the 5 words of the shorter statement are in the longer one (0.6).
# Over the 30 distinct live subjects the other matches are 263 (the same performance history, 0.75) and 52~187
# ("only file edits are reality-checked" reworded after a fix, 0.63 of the shorter statement); different subjects
# stay below both: similarity at most 0.39, and at most 0.5 of
# the shorter statement inside the same component (e.g. "GPU is not probed" vs "GPU load ... only on NVIDIA").
MIN_SHARED_WORDS = 3  # a two-word statement is not "contained" in every subject that names its topic


def _component(subject: str) -> tuple:
    head, sep, rest = subject.partition(": ")
    return (head.strip().lower(), rest) if sep else ("", subject)


def similar_subject(a: str, b: str) -> bool:
    """True when known-limitation subject a is b reworded: consolidate.similarity >= SIMILAR over the whole
    subjects, or, within the same component, the shorter statement's words share at least SIMILAR of
    themselves (and MIN_SHARED_WORDS) with the longer one's."""
    from syrax.consolidate import SIMILAR, _words, similarity

    if not a or not b:
        return False
    if a == b or similarity(a, b) >= SIMILAR:
        return True
    (ca, da), (cb, db) = _component(a), _component(b)
    if ca != cb:
        return False
    wa, wb = _words(da), _words(db)
    shared = len(wa & wb)
    return shared >= MIN_SHARED_WORDS and shared / min(len(wa), len(wb)) >= SIMILAR


def already_researched(subject: str, researched: set) -> bool:
    return subject in researched or any(similar_subject(subject, r) for r in researched)


def choose(journal: Journal, selfmodel: Any, now: Optional[float] = None) -> Optional[dict]:
    """Create an objective for the strongest limitation not yet offered this
    week. Returns the created objective, or None."""
    ranked = rank(journal, selfmodel, now)
    week = _week(now)
    chosen = None
    # With repro hunts on (repro.py), a tool's own failures are hunted with a proof, and a limitation already
    # researched stays researched: 14 days to 2026-10-22 spent ~1000 brain calls on tool_reliability, repair and
    # weekly re-research objectives that changed nothing (34 known-limitation objectives on recurring subjects).
    from syrax import repro

    hunting = repro.enabled()
    researched = researched_subjects(journal, now) if hunting else set()
    for lim in ranked:
        if hunting and (lim["kind"] == "tool_reliability" or (lim["kind"] == "known_limitation" and already_researched(lim["subject"], researched))):
            continue
        key = f"limit:{lim['kind']}:{lim['subject']}:{week}"
        obj = journal.add_objective_sync(
            goal=f"My biggest measured limitation right now: {lim['detail']}. Improve it. Plan: " + " ".join(f"({i + 1}) {s}" for i, s in enumerate(lim["plan"])),
            reason=f"ranked first of {len(ranked)} limitations by evidence (score {lim['score']})",
            priority=3,
            source="selfmodel",
            check=lim["check"],
            key=key,
            evidence={"limitation": {k: lim[k] for k in ("kind", "subject", "score", "detail")}, "plan": lim["plan"],
                      "plan_checks": lim.get("plan_checks") or [], **lim["evidence"]},
            next_action=lim["plan"][0],
        )
        if obj:
            chosen = {**lim, "objective_id": obj["id"], "key": key}
            break
    journal.record_sync("limitation.ranked", {
        "ranked": [{k: x.get(k) for k in ("kind", "subject", "score", "confidence", "explore_bonus", "cost", "value", "detail")} for x in ranked[:8]],
        "chosen": {k: chosen[k] for k in ("kind", "subject", "score", "objective_id")} if chosen else None,
    })
    return chosen


def judge_tool_reliability(journal: Journal, objective: dict) -> tuple:
    spec = objective.get("check_spec") or {}
    tool = spec.get("tool")
    ok = bad = 0
    # "New uses" are the events after the objective's own creation event, by
    # id: on Windows time.time() ticks every ~15 ms, so uses recorded in the
    # same tick as the objective passed a ts >= created filter (gate run,
    # 2026-10-03) and counted old failures against the fix.
    # Only the two kinds of event the verdict needs, newest first. It read the whole journal
    # window before: events_between's first 10 000 events after an old objective missed every
    # newer use, and each cycle re-read ~15 000 events per BLOCKED objective (2026-10-13).
    since = objective["created"] - 1
    born = next((e["id"] for e in journal.events_of_type("objective.created", since=since, limit=5000)
                 if e["payload"].get("objective_id") == objective.get("id")), None)
    is_probe = probe_tasks(journal)
    for kind in ("tool.completed", "tool.failed"):
        for e in journal.events_of_type(kind, since=since, limit=5000):
            if (born is not None and e["id"] <= born) or e["payload"].get("name") != tool or refused(e["payload"]):
                continue  # before the objective, another tool, or a call a guard refused (not the tool failing)
            if is_probe(e.get("task_id")):
                continue  # a quality case's use is neither a new failure nor a new success of the fix
            if kind == "tool.completed":
                ok += 1
            else:
                bad += 1
    uses = ok + bad
    rate = bad / uses if uses else None
    need = int(spec.get("min_uses") or MIN_USES)
    met = uses >= need and rate is not None and rate <= float(spec.get("max_rate") or 0.1)
    return ("DONE" if met else "RETRY"), {"tool": tool, "uses_since": uses, "failures_since": bad, "rate_since": rate, "needed_uses": need, "max_rate": spec.get("max_rate")}
