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
from typing import Any, Dict, List, Optional

from syrax.journal import Journal

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


def recent_tool_stats(journal: Journal, per_tool: int = RECENT_USES) -> Dict[str, dict]:
    """successes/failures over each tool's latest ``per_tool`` outcomes.
    Live: str_replace_editor was 5 % in the last 4 h after its fix but still
    ranked first on its all-time 20 %."""
    outcomes: Dict[str, List[bool]] = {}
    for e in reversed(journal.recent_events(5000)):
        if e["type"] not in ("tool.completed", "tool.failed"):
            continue
        name = e["payload"].get("name")
        lst = outcomes.setdefault(name, [])
        if len(lst) < per_tool:
            lst.append(e["type"] == "tool.completed")
    return {n: {"successes": sum(v), "failures": len(v) - sum(v), "window": per_tool} for n, v in outcomes.items() if n}


def rank(journal: Journal, selfmodel: Any, now: Optional[float] = None) -> List[dict]:
    """Every measurable limitation, strongest first."""
    now = now or time.time()
    out: List[dict] = []
    for tool, st in recent_tool_stats(journal).items():
        done = st["successes"] + st["failures"]
        if tool in SKIP_TOOLS or done < MIN_USES:
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
        })
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
        })
    try:
        weaknesses = selfmodel.weaknesses()
    except Exception:
        weaknesses = []
    since = now - 86400
    known_today = sum(1 for o in journal.objectives(limit=200)
                      if (o.get("key") or "").startswith("limit:known_limitation:") and o["created"] >= since)
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
        })
    out.sort(key=lambda x: -x["score"])
    return out


def choose(journal: Journal, selfmodel: Any, now: Optional[float] = None) -> Optional[dict]:
    """Create an objective for the strongest limitation not yet offered this
    week. Returns the created objective, or None."""
    ranked = rank(journal, selfmodel, now)
    week = _week(now)
    chosen = None
    for lim in ranked:
        key = f"limit:{lim['kind']}:{lim['subject']}:{week}"
        obj = journal.add_objective_sync(
            goal=f"My biggest measured limitation right now: {lim['detail']}. Improve it. Plan: " + " ".join(f"({i + 1}) {s}" for i, s in enumerate(lim["plan"])),
            reason=f"ranked first of {len(ranked)} limitations by evidence (score {lim['score']})",
            priority=3,
            source="selfmodel",
            check=lim["check"],
            key=key,
            evidence={"limitation": {k: lim[k] for k in ("kind", "subject", "score", "detail")}, "plan": lim["plan"], **lim["evidence"]},
            next_action=lim["plan"][0],
        )
        if obj:
            chosen = {**lim, "objective_id": obj["id"], "key": key}
            break
    journal.record_sync("limitation.ranked", {
        "ranked": [{k: x[k] for k in ("kind", "subject", "score", "detail")} for x in ranked[:8]],
        "chosen": {k: chosen[k] for k in ("kind", "subject", "score", "objective_id")} if chosen else None,
    })
    return chosen


def judge_tool_reliability(journal: Journal, objective: dict) -> tuple:
    spec = objective.get("check_spec") or {}
    tool = spec.get("tool")
    ok = bad = 0
    for e in journal.events_between(objective["created"], limit=10000):
        if e["type"] in ("tool.completed", "tool.failed") and e["payload"].get("name") == tool:
            if e["type"] == "tool.completed":
                ok += 1
            else:
                bad += 1
    uses = ok + bad
    rate = bad / uses if uses else None
    need = int(spec.get("min_uses") or MIN_USES)
    met = uses >= need and rate is not None and rate <= float(spec.get("max_rate") or 0.1)
    return ("DONE" if met else "RETRY"), {"tool": tool, "uses_since": uses, "failures_since": bad, "rate_since": rate, "needed_uses": need, "max_rate": spec.get("max_rate")}
