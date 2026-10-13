"""Reminders: "remind me at 5 to call Rahim".

Kept in the journal as reminder.created / reminder.fired / reminder.cancelled
events, so they survive a restart and the pending list is a pure function of
the record. SYRAX's own loop fires them: a journaled `reminder.fired` (which
the UI shows and speaks), and a desktop notification. A reminder that fell due
while SYRAX was off fires at the next start and says how late it is. No
operating-system scheduled tasks are created.

From the feature catalog (2026-10-12); the idea came from the surveyed JARVIS
assistants, the code is SYRAX's own.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic import Field

from app.tool.base import BaseTool, ToolResult
from syrax.journal import Journal, get_journal

CHECK_EVERY_S = 15.0
MAX_TEXT = 300
MAX_AHEAD_S = 366 * 86400


def pending(journal: Journal) -> List[Dict[str, Any]]:
    """Reminders created and neither fired nor cancelled, soonest first."""
    done = {e["payload"].get("id") for t in ("reminder.fired", "reminder.cancelled")
            for e in journal.events_of_type(t, limit=5000)}
    out = [dict(e["payload"]) for e in journal.events_of_type("reminder.created", limit=5000)
           if e["payload"].get("id") not in done]
    return sorted(out, key=lambda r: float(r.get("due_ts") or 0))


def parse_when(at: Optional[str] = None, in_minutes: Optional[float] = None, now: Optional[float] = None) -> float:
    """The due time as a timestamp: `in_minutes` from now, or `at` in local time
    ('17:30' today, or tomorrow when that has passed; or '2026-10-12T17:30')."""
    now = now if now is not None else time.time()
    if in_minutes is not None and str(in_minutes).strip() != "":
        minutes = float(in_minutes)
        if minutes <= 0:
            raise ValueError("in_minutes must be more than 0")
        return now + minutes * 60
    text = str(at or "").strip()
    if not text:
        raise ValueError("say when: `at` (local time like 17:30 or 2026-10-12T17:30) or `in_minutes`")
    base = dt.datetime.fromtimestamp(now)
    try:
        if "T" in text or "-" in text:
            when = dt.datetime.fromisoformat(text.replace(" ", "T"))
            if when.tzinfo is not None:
                return when.timestamp()
        else:
            hh, _, mm = text.partition(":")
            when = base.replace(hour=int(hh), minute=int(mm or 0), second=0, microsecond=0)
            if when.timestamp() <= now:
                when += dt.timedelta(days=1)
    except ValueError:
        raise ValueError(f"cannot read the time {text!r}; use 17:30 or 2026-10-12T17:30")
    ts = when.timestamp()
    if ts <= now:
        raise ValueError(f"{text} has already passed")
    return ts


def create(journal: Journal, text: str, due_ts: float, now: Optional[float] = None) -> Dict[str, Any]:
    text = " ".join(str(text or "").split())[:MAX_TEXT]
    if not text:
        raise ValueError("a reminder needs its text")
    now = now if now is not None else time.time()
    if due_ts - now > MAX_AHEAD_S:
        raise ValueError("a reminder can be at most a year ahead")
    r = {"id": uuid.uuid4().hex[:8], "text": text, "due_ts": round(float(due_ts), 3), "created_ts": round(now, 3)}
    journal.record_sync("reminder.created", r)
    return r


def cancel(journal: Journal, rid: str) -> bool:
    if not any(r["id"] == rid for r in pending(journal)):
        return False
    journal.record_sync("reminder.cancelled", {"id": rid})
    return True


def when_text(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


async def fire_due(journal: Journal, notify: Optional[Callable[[str], Awaitable[Any]]] = None,
                   now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Fire every pending reminder that is due. Each one is journaled before the
    notification, so a crash in between never fires it twice."""
    now = now if now is not None else time.time()
    fired = []
    # off the event loop: a slow journal call elsewhere holds the journal lock, and waiting for it
    # here froze the whole server for 60 s+ (stall-20261012-184441.txt)
    for r in await asyncio.to_thread(pending, journal):
        if float(r.get("due_ts") or 0) > now:
            break
        late = max(0, int(now - float(r["due_ts"])))
        payload = {"id": r["id"], "text": r["text"], "due_ts": r["due_ts"], "late_s": late}
        await journal.record("reminder.fired", payload)  # fans out: the UI shows and speaks it
        fired.append(payload)
        if notify is not None:
            try:
                await notify(r["text"] + (f" (late by {late // 60} min)" if late >= 120 else ""))
            except Exception:  # the journal and the UI already have it
                pass
    return fired


async def loop(journal: Journal, notify: Optional[Callable[[str], Awaitable[Any]]] = None,
               every: float = CHECK_EVERY_S) -> None:
    while True:
        try:
            await fire_due(journal, notify)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(every)


async def desktop_notify(text: str) -> None:
    from syrax.desktop import DesktopControl

    await DesktopControl()._do_notify(value=f"Reminder: {text}")


class RemindTool(BaseTool):
    name: str = "remind"
    description: str = (
        "Reminders for the human. action=set with `text` and either `at` (local time, e.g. 17:30 or "
        "2026-10-12T17:30) or `in_minutes`; action=list shows the pending ones; action=cancel with `id`. "
        "SYRAX fires a reminder itself at its time (a spoken line, a notice and a desktop notification), "
        "also after a restart."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["set", "list", "cancel"]},
            "text": {"type": "string", "description": "what to remind, for set"},
            "at": {"type": "string", "description": "local time for set: HH:MM or YYYY-MM-DDTHH:MM"},
            "in_minutes": {"type": "number", "description": "for set: minutes from now"},
            "id": {"type": "string", "description": "reminder id, for cancel"},
        },
        "required": ["action"],
    }
    journal_provider: Callable[[], Journal] = Field(default=get_journal, exclude=True)

    async def execute(self, action: str, text: str = "", at: Optional[str] = None,
                      in_minutes: Optional[float] = None, id: str = "") -> ToolResult:
        journal = self.journal_provider()
        try:
            if action == "set":
                r = await asyncio.to_thread(create, journal, text, parse_when(at, in_minutes))
                return ToolResult(output=f"Reminder {r['id']} set for {when_text(r['due_ts'])}: {r['text']}")
            if action == "list":
                rows = await asyncio.to_thread(pending, journal)
                if not rows:
                    return ToolResult(output="No pending reminders.")
                return ToolResult(output="\n".join(f"{r['id']} · {when_text(r['due_ts'])} · {r['text']}" for r in rows))
            if action == "cancel":
                ok = await asyncio.to_thread(cancel, journal, id)
                return ToolResult(output=f"Reminder {id} cancelled.") if ok else ToolResult(error=f"no pending reminder {id!r}")
            return ToolResult(error="action must be set, list or cancel")
        except ValueError as e:
            return ToolResult(error=f"remind: {e}")
