"""SYRAX's daily briefing: what it did, learned and proposes since the human
last looked — composed from the journal, no model call, so it costs no quota
and claims nothing the journal does not show.

Shown once a day on the stage when a session opens (journal meta
`briefing_last`), and on request over the WebSocket (`briefing {hours?}`).
Idea from Brahma AI - Lite's morning briefing.
"""

from __future__ import annotations

import os
import time
from collections import Counter
from typing import Optional

from syrax.journal import Journal

EVERY_S = 12 * 3600.0
META_KEY = "briefing_last"


def compose(journal: Journal, since: Optional[float] = None, now: Optional[float] = None) -> str:
    now = now or time.time()
    since = since if since is not None else now - 24 * 3600
    events = journal.events_between(since, now, limit=10000)
    kinds = Counter(e["type"] for e in events)
    hours = max(1, round((now - since) / 3600))
    lines = [f"Since {time.strftime('%a %H:%M', time.localtime(since))} ({hours} h):"]

    done = kinds.get("task.completed", 0)
    failed = kinds.get("task.failed", 0)
    lines.append(f"- tasks: {done} finished, {failed} failed")

    closed = [e["payload"] for e in events if e["type"] == "objective.completed"]
    if closed:
        names = []
        for p in closed[:5]:
            o = journal.objective(p.get("objective_id")) or {}
            names.append(f"#{p.get('objective_id')} {str(o.get('goal') or '')[:70]}")
        lines.append(f"- objectives closed: {len(closed)}" + "".join(f"\n    {n}" for n in names))
    blocked = sum(1 for e in events if e["type"] == "objective.blocked")
    if blocked:
        lines.append(f"- objectives blocked: {blocked} (a different strategy or a human is needed)")

    learned = sorted({str(e["payload"].get("skill") or e["payload"].get("name")) for e in events if e["type"] == "skill.verified"})
    learned = [s for s in learned if s and s != "None"]
    if learned:
        lines.append(f"- new skills: {', '.join(learned)}")

    commits = [e["payload"] for e in events if e["type"] == "commit.created"]
    if commits:
        lines.append(f"- self-modifications released: {len(commits)}" + "".join(f"\n    {str(c.get('commit'))[:8]} {str(c.get('summary'))[:70]}" for c in commits[:3]))

    proposals = [e["payload"] for e in events if e["type"] == "proposal.created"]
    if proposals:
        lines.append(f"- proposals for you: {len(proposals)}" + "".join(f"\n    {str(p.get('limitation'))[:60]}: {str(p.get('proposal'))[:110]}" for p in proposals[:3]))

    runs = journal.quality_runs(limit=1)
    if runs and runs[0]["ts"] >= since:
        r = runs[0]
        failed_cases = [x["id"] for x in r["results"] if not x.get("ok")]
        lines.append(f"- quality: {r['pass_rate']}%" + (f" (failing: {', '.join(failed_cases)})" if failed_cases else ""))

    answered, failovers = kinds.get("brain.answered", 0), kinds.get("brain.failover", 0)
    if answered + failovers:
        lines.append(f"- brains: {answered} answers, {failovers} failovers")
    try:
        from syrax import scorecard

        card = scorecard.compute(journal)
        best = sorted((p for p in card if card[p]["graded"] >= 5), key=lambda p: -card[p]["quality"])
        if best:
            lines.append("- brain quality (graded tasks): " + ", ".join(f"{p} {card[p]['quality']:.0%}" for p in best[:4]))
    except Exception:
        pass
    restarts = kinds.get("restart.requested", 0)
    if restarts:
        lines.append(f"- restarted itself into new code {restarts} time(s)")

    open_n = len(journal.objectives(limit=200, status=["OPEN", "ACTIVE"]))
    lines.append(f"- open objectives now: {open_n}")
    return "\n".join(lines)


def due(journal: Journal, now: Optional[float] = None) -> bool:
    if os.getenv("SYRAX_BRIEFING", "1") == "0":
        return False
    now = now or time.time()
    try:
        last = float(journal.get_meta(META_KEY) or 0)
    except ValueError:
        last = 0.0
    return now - last >= EVERY_S


def mark_shown(journal: Journal, now: Optional[float] = None) -> None:
    journal.set_meta(META_KEY, str(now or time.time()))
