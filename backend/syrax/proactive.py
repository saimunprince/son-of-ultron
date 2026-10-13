"""Proactive check-ins: SYRAX speaks up when it has something useful, and
stays quiet otherwise.

Every CHECK_EVERY_S the loop reads the journal. When the human has not talked
for QUIET_FOR_S, it is daytime (DAY hours, local) and outside quiet hours, and
the last check-in was more than COOLDOWN_S ago, it gathers what the human has
not been told since they last talked: skills SYRAX built and objectives it
closed on its own, reminders due within the hour, system alerts. Nothing to
say means nothing is said. Otherwise one short check-in is journaled
(`checkin.made` {text, items}); the UI shows and speaks it.

No model writes it: the sentence is built from the journal.

From the feature catalog (proactive); the idea came from the surveyed JARVIS
assistants, the code is SYRAX's own.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Any, Dict, List, Optional

from syrax.journal import Journal

CHECK_EVERY_S = 300.0
QUIET_FOR_S = 2 * 3600.0
COOLDOWN_S = 4 * 3600.0
DAY = (8, 22)
MAX_ITEMS = 4


def last_human(journal: Journal) -> float:
    for t in journal.tasks(limit=100):
        if t.get("kind") == "conversation":
            return float(t.get("updated") or t.get("created") or 0)
    return 0.0


def last_checkin(journal: Journal) -> float:
    rows = journal.events_of_type("checkin.made", limit=1)
    return float(rows[-1]["ts"]) if rows else 0.0


def gather(journal: Journal, since: float, now: float) -> List[str]:
    from syrax import reminders

    items: List[str] = []
    built = sorted({str(e["payload"].get("skill")) for e in journal.events_of_type("skill.verified", since=since, limit=200)
                    if e["payload"].get("skill")})
    if built:
        items.append("I built and verified " + ", ".join(built[:3]) + (" and more" if len(built) > 3 else ""))
    closed = [e for e in journal.events_of_type("objective.completed", since=since, limit=200)]
    if closed:
        items.append(f"I closed {len(closed)} objective{'s' if len(closed) != 1 else ''} on my own")
    for r in reminders.pending(journal):
        if now < float(r["due_ts"]) <= now + 3600:
            items.append(f"reminder at {dt.datetime.fromtimestamp(r['due_ts']).strftime('%H:%M')}: {r['text']}")
    for e in journal.events_of_type("alert.raised", since=since, limit=20):
        items.append(str(e["payload"].get("detail")))
    return items[:MAX_ITEMS]


def compose(items: List[str]) -> str:
    return "While you were away: " + "; ".join(items) + "."


def daytime(now: float) -> bool:
    return DAY[0] <= dt.datetime.fromtimestamp(now).hour < DAY[1]


async def tick(journal: Journal, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    from syrax import resources

    now = now if now is not None else time.time()
    # every journal read off the event loop: waiting on the journal lock must not freeze the server
    human = await asyncio.to_thread(last_human, journal)
    if now - human < QUIET_FOR_S or not daytime(now) or resources.in_quiet_hours(dt.datetime.fromtimestamp(now).hour):
        return None
    previous = await asyncio.to_thread(last_checkin, journal)
    if now - previous < COOLDOWN_S:
        return None
    items = await asyncio.to_thread(gather, journal, max(human, previous), now)
    if not items:
        return None  # nothing useful: silence is the answer
    payload = {"text": compose(items), "items": items}
    await journal.record("checkin.made", payload)  # fans out: the UI shows and speaks it
    return payload


async def loop(journal: Journal, every: float = CHECK_EVERY_S) -> None:
    while True:
        try:
            await tick(journal)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(every)
