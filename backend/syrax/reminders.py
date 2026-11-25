"""Reminders: "remind me at 5 to call Rahim".

Kept in the journal as reminder.created / reminder.fired / reminder.cancelled
events, so they survive a restart and the pending list is a pure function of
the record. SYRAX's own loop fires them: a journaled `reminder.fired` (which
the UI shows and speaks), and a desktop notification. A reminder that fell due
while SYRAX was off fires at the next start and says how late it is. No
operating-system scheduled tasks are created.

From the feature catalog (2026-10-12); the idea came from the surveyed JARVIS
assistants, the code is SYRAX's own.

2026-11-25, one routines engine (idea from the Mark-LVII JARVIS project, the code
is SYRAX's own): the same rows also hold `monthly` rules (a day of month, or
`last`) and `interval` rules (every N minutes between two times of day), and
`daily` / `interval` may be limited to chosen weekdays. A run later than its
action's lateness limit (LATE_LIMIT_S) is skipped and journaled
`reminder.skipped` instead of firing hours late, and a repeating rule only ever
sets its next run after now, so a long gap never fires a burst. A rule with no
time of day the human chose (an interval) skips its runs in quiet hours
(SYRAX_QUIET_HOURS, off by default); an explicitly timed reminder still rings.
A routine may start a SYRAX task instead of speaking (`action: task`): nobody
watches it, so it runs as ROUTINE_KIND ("autonomous"), the kind that refuses
system, external-write and destructive actions. Old rows (id, text, due_ts,
created_ts, repeat daily/weekly) load and fire unchanged.
"""

from __future__ import annotations

import asyncio
import calendar
import datetime as dt
import logging
import math
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Union

from pydantic import Field

from app.tool.base import BaseTool, ToolResult
from syrax.journal import Journal, get_journal

log = logging.getLogger(__name__)

CHECK_EVERY_S = 15.0
MAX_TEXT = 300
MAX_AHEAD_S = 366 * 86400
# Live 2026-11-06: "remind me every day at 9 AM to drink water" set one reminder for tomorrow and the answer said
# "daily". A repeating reminder sets its next one when it fires.
REPEATS = {"daily": 86400, "weekly": 7 * 86400}
# 2026-11-25 (routines engine): monthly = the same day of month (31 in a short month is its last day, or `last`);
# interval = every N minutes from `start` to `end` (local times of day), on `weekdays` when given.
RULES = ("daily", "weekly", "monthly", "interval")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MIN_EVERY_MIN, MAX_EVERY_MIN = 5, 720
# Every run is two journal events (created, then fired or skipped) and pending() reads the newest 5000 creations, so a
# dense rule would push a reminder set months ahead out of that window: at most this many runs a day.
MAX_RUNS_A_DAY = 48
# A run later than this (SYRAX was off) is skipped, not fired: a spoken line hours late is noise, and a task 6 h
# late may do the right thing at the wrong time.
LATE_LIMIT_S = {"speak": 2 * 3600, "task": 6 * 3600}
ACTIONS = tuple(LATE_LIMIT_S)
# An unattended routine task: the kind permissions.decide refuses system, external-write and destructive actions
# for, held to the operator's autonomy level, and blocked by the emergency stop (estop.BLOCKED_KINDS).
ROUTINE_KIND = "autonomous"
ROUTINE_NOTE = ("\n\n(Started by a routine the human set earlier; nobody is watching. Do only safe, local, reversible "
                "steps, and name in your final answer anything more a human should do.)")


def pending(journal: Journal) -> List[Dict[str, Any]]:
    """Reminders created and neither fired, skipped nor cancelled, soonest first."""
    done = {e["payload"].get("id") for t in ("reminder.fired", "reminder.skipped", "reminder.cancelled")
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


def _clock(text: str) -> dt.time:
    hh, _, mm = str(text).strip().partition(":")
    try:
        return dt.time(int(hh), int(mm or 0))
    except ValueError:
        raise ValueError(f"cannot read the time of day {text!r}; use HH:MM")


def _weekdays(value: Union[str, Iterable[Any], None]) -> List[int]:
    """'mon,wed,fri', 'mon-fri', 'weekdays', 'weekends' or [0, 2, 4] → sorted weekday numbers (Monday 0)."""
    if value is None or value == "" or value == []:
        return []
    if isinstance(value, str):
        text = value.strip().lower().replace(" ", "")
        text = {"weekdays": "mon-fri", "workdays": "mon-fri", "weekends": "sat,sun", "weekend": "sat,sun"}.get(text, text)
        out: set = set()
        for part in filter(None, text.split(",")):
            a, _, b = part.partition("-")
            try:
                i, k = DAYS.index(a[:3]), DAYS.index((b or a)[:3])
            except ValueError:
                raise ValueError(f"cannot read the weekday {part!r}; use mon,tue,...,sun or mon-fri")
            out.update(range(i, k + 1) if i <= k else [*range(i, 7), *range(0, k + 1)])
        return sorted(out)
    days = sorted({int(d) for d in value})
    if any(not 0 <= d <= 6 for d in days):
        raise ValueError("weekdays are 0 (Monday) to 6 (Sunday)")
    return days


def _rule(repeat: str, day: Any = None, every_min: Any = None, between: Optional[str] = None,
          weekdays: Any = None) -> Dict[str, Any]:
    """The stored fields of a repeat rule (empty for once), checked."""
    repeat = (repeat or "").strip().lower()
    if repeat in ("none", "once", "no"):
        repeat = ""
    if repeat and repeat not in RULES:
        raise ValueError(f"repeat must be one of: {', '.join(RULES)} (or leave it out for once)")
    if not repeat:
        return {}
    r: Dict[str, Any] = {"repeat": repeat}
    if repeat == "monthly" and day not in (None, ""):
        d: Any = str(day).strip().lower()
        if d != "last":
            try:
                d = int(float(d))
            except ValueError:
                raise ValueError("day must be 1-31 or last")
            if not 1 <= d <= 31:
                raise ValueError("day must be 1-31 or last")
        r["day"] = d
    if repeat == "interval":
        try:
            every = int(float(every_min))
        except (TypeError, ValueError):
            raise ValueError("an interval rule needs every_minutes")
        if not MIN_EVERY_MIN <= every <= MAX_EVERY_MIN:
            raise ValueError(f"every_minutes must be {MIN_EVERY_MIN}-{MAX_EVERY_MIN}")
        a, _, b = str(between or "00:00-23:59").partition("-")
        start, end = _clock(a), _clock(b or "23:59")
        if end <= start:
            raise ValueError("between must be a start before an end on the same day, e.g. 09:00-17:00")
        span = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
        if span // every + 1 > MAX_RUNS_A_DAY:
            raise ValueError(f"at most {MAX_RUNS_A_DAY} runs a day: a longer every_minutes or a shorter between")
        # no time of day the human chose for each run: quiet hours apply to it
        r.update({"every_min": every, "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M"), "untimed": True})
    days = _weekdays(weekdays)
    if days and len(days) < 7:
        if repeat not in ("daily", "interval"):
            raise ValueError("weekdays go with repeat daily or interval")
        r["weekdays"] = days
    return r


def create(journal: Journal, text: str, due_ts: Optional[float], now: Optional[float] = None, repeat: str = "",
           *, day: Any = None, every_min: Any = None, between: Optional[str] = None, weekdays: Any = None,
           action: str = "", task: str = "") -> Dict[str, Any]:
    """A reminder or a routine. `due_ts` is the first run, and its local time of day is the rule's time; a monthly,
    weekday or interval rule moves it to the rule's first run from now. An interval needs no `due_ts`. A `task`
    makes the action "task" (start it as SYRAX's own unattended task) unless `action` says otherwise."""
    text = " ".join(str(text or "").split())[:MAX_TEXT]
    task = " ".join(str(task or "").split())[:MAX_TEXT]
    action = (action or ("task" if task else "speak")).strip().lower()
    if action not in ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(ACTIONS)}")
    if action == "task":
        task = task or text
        if not task:
            raise ValueError("a task routine needs its instruction")
    text = text or task
    if not text:
        raise ValueError("a reminder needs its text")
    rule = _rule(repeat, day, every_min, between, weekdays)
    now = now if now is not None else time.time()
    if due_ts is None:
        if rule.get("repeat") != "interval":
            raise ValueError("say when: `at` (local time like 17:30 or 2026-10-12T17:30) or `in_minutes`")
        due_ts = now
    if rule.get("repeat") == "monthly" and "day" not in rule:
        rule["day"] = dt.datetime.fromtimestamp(due_ts).day
    if rule.get("repeat") in ("monthly", "interval") or rule.get("weekdays"):
        due_ts = next_run({**rule, "due_ts": due_ts}, now, first=True)
    if due_ts - now > MAX_AHEAD_S:
        raise ValueError("a reminder can be at most a year ahead")
    r = {"id": uuid.uuid4().hex[:8], "text": text, "due_ts": round(float(due_ts), 3), "created_ts": round(now, 3)}
    r.update(rule)  # a once, daily or weekly reminder gets exactly the fields it always had
    if action == "task":
        r.update({"action": "task", "task": task})
    journal.record_sync("reminder.created", r)
    return r


def _at(day: dt.date, tod: dt.time) -> float:
    return dt.datetime.combine(day, tod).timestamp()


def next_run(r: Dict[str, Any], after: float, first: bool = False) -> float:
    """The rule's first run strictly after `after` (local time). Without `first` it is also after the run that just
    fell due (`due_ts`); with it (creating) `due_ts` only gives the time of day. Days SYRAX was off are passed over."""
    repeat = r.get("repeat")
    due = float(r["due_ts"])
    tod = dt.datetime.fromtimestamp(due).time().replace(microsecond=0)
    if repeat in REPEATS and not r.get("weekdays"):
        # the old rows' arithmetic, unchanged
        step = REPEATS[repeat]
        nxt = due if first else due + step
        while nxt <= after:
            nxt += step
        return nxt
    after = after if first else max(after, due)
    days = set(r.get("weekdays") or range(7))
    start = dt.datetime.fromtimestamp(after).date()
    if repeat == "daily":
        for i in range(9):
            day = start + dt.timedelta(days=i)
            if day.weekday() in days and (ts := _at(day, tod)) > after:
                return ts
    if repeat == "monthly":
        want = r.get("day") or dt.datetime.fromtimestamp(due).day
        y, m = start.year, start.month
        for _ in range(14):
            last = calendar.monthrange(y, m)[1]
            if (ts := _at(dt.date(y, m, last if want == "last" else min(int(want), last)), tod)) > after:
                return ts
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    if repeat == "interval":
        step = int(r["every_min"]) * 60
        s_t, e_t = _clock(r["start"]), _clock(r["end"])
        for i in range(9):
            day = start + dt.timedelta(days=i)
            if day.weekday() not in days:
                continue
            s_ts, e_ts = _at(day, s_t), _at(day, e_t)
            ts = s_ts if after < s_ts else s_ts + (math.floor((after - s_ts) / step) + 1) * step
            if ts <= e_ts:
                return ts
    raise ValueError(f"no next run for the rule {repeat!r}")


def next_due(due_ts: float, repeat: str, now: float) -> float:
    """The next time a daily or weekly reminder is due after `now` (a day it was off is skipped, not fired late)."""
    return next_run({"due_ts": due_ts, "repeat": repeat}, now)


def cancel(journal: Journal, rid: str) -> bool:
    if not any(r["id"] == rid for r in pending(journal)):
        return False
    journal.record_sync("reminder.cancelled", {"id": rid})
    return True


def when_text(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def repeat_text(r: Dict[str, Any]) -> str:
    rule = r.get("repeat")
    if rule == "interval":
        out = f", then every {r.get('every_min')} min {r.get('start')}-{r.get('end')}"
    elif rule == "monthly":
        out = f", then monthly on day {r.get('day')}"
    else:
        out = f", then {rule}" if rule else ""
    if r.get("weekdays"):
        out += " on " + ",".join(DAYS[d] for d in r["weekdays"])
    return out + (" (starts a task)" if r.get("action") == "task" else "")


def quiet_now(now: float) -> bool:
    from syrax import resources

    return resources.in_quiet_hours(dt.datetime.fromtimestamp(now).hour)


StartTask = Callable[[str], Awaitable[Optional[str]]]


async def fire_due(journal: Journal, notify: Optional[Callable[[str], Awaitable[Any]]] = None,
                   now: Optional[float] = None, start_task: Optional[StartTask] = None) -> List[Dict[str, Any]]:
    """Fire every pending reminder that is due. Each one is journaled before the
    notification, so a crash in between never fires it twice.

    2026-11-25 (routines engine): a run later than its action's limit, or an untimed run in quiet hours, is journaled
    `reminder.skipped` instead; either way a repeating rule then sets its one next run after now (never a burst). A
    task routine calls `start_task(instruction)`: a task id fires it, None (SYRAX busy) waits for the next check, a
    PermissionError (the emergency stop) or any other failure skips the run."""
    now = now if now is not None else time.time()
    fired = []
    # off the event loop: a slow journal call elsewhere holds the journal lock, and waiting for it
    # here froze the whole server for 60 s+ (stall-20261012-184441.txt)
    for r in await asyncio.to_thread(pending, journal):
        if float(r.get("due_ts") or 0) > now:
            break
        late = max(0, int(now - float(r["due_ts"])))
        action = r.get("action") if r.get("action") in ACTIONS else "speak"
        payload = {"id": r["id"], "text": r["text"], "due_ts": r["due_ts"], "late_s": late}
        why, task_id = "", None
        if late > LATE_LIMIT_S[action]:
            why = f"late by {late // 60} min, over the {LATE_LIMIT_S[action] // 3600} h limit"
        elif r.get("untimed") and quiet_now(now):
            why = "quiet hours"
        elif action == "task":
            if start_task is None:
                why = "no task runner"
            else:
                try:
                    task_id = await start_task(r.get("task") or r["text"])
                except PermissionError as e:
                    why = f"task refused: {e}"
                except Exception as e:  # a broken runner must not stop the other reminders
                    why = f"task did not start: {e}"[:200]
                else:
                    if task_id is None:
                        continue  # SYRAX is busy: the next check tries again (the lateness limit still holds)
        if why:
            await journal.record("reminder.skipped", {**payload, "reason": why})  # the UI shows it, never speaks it
            log.info("reminder %s skipped: %s", r["id"], why)
        else:
            if action == "task":
                payload.update({"action": "task", "task_id": task_id})
            await journal.record("reminder.fired", payload)  # fans out: the UI shows and speaks it
            fired.append(payload)
        if r.get("repeat") in RULES:
            try:
                await asyncio.to_thread(_again, journal, r, now)
            except Exception as e:
                log.warning("reminder %s: could not set its next run: %s", r["id"], e)
        if why or notify is None:
            continue
        try:
            note = ("Routine started: " if action == "task" else "") + r["text"]
            await notify(note + (f" (late by {late // 60} min)" if late >= 120 else ""))
        except Exception:  # the journal and the UI already have it
            pass
    return fired


def _again(journal: Journal, r: Dict[str, Any], now: float) -> Dict[str, Any]:
    """The rule's next row: the same fields, a new id, the next run after now."""
    nxt = {**r, "id": uuid.uuid4().hex[:8], "due_ts": round(next_run(r, now), 3), "created_ts": round(now, 3)}
    journal.record_sync("reminder.created", nxt)
    return nxt


async def start_routine_task(core: Any, instruction: str) -> Optional[str]:
    """The hook that starts a routine's task. Nobody is watching it, so it runs as ROUTINE_KIND, never as the human's
    conversation. None while SYRAX is busy (the routine waits); PermissionError while the emergency stop is on."""
    from syrax import estop

    if await asyncio.to_thread(estop.active, core.journal):
        raise PermissionError("the emergency stop is on")
    if core.busy:
        return None
    return await core.submit(instruction + ROUTINE_NOTE, said=instruction, session_id=None, kind=ROUTINE_KIND)


async def loop(journal: Journal, notify: Optional[Callable[[str], Awaitable[Any]]] = None,
               every: float = CHECK_EVERY_S, start_task: Optional[StartTask] = None) -> None:
    while True:
        try:
            await fire_due(journal, notify, start_task=start_task)
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
        "Reminders and routines for the human. action=set with `text` and either `at` (local time, e.g. 17:30 or "
        "2026-10-12T17:30) or `in_minutes`, and `repeat` only when the human says it repeats (without it the "
        "reminder fires once: never call a reminder daily unless repeat is set): daily, weekly, monthly (`day` 1-31 "
        "or last; 31 fires on a short month's last day) or interval (`every_minutes` with `between` like 09:00-17:00, "
        "no `at`); `weekdays` (mon-fri, sat,sun) limits daily or interval. `task` = an instruction SYRAX runs as its "
        "own unattended task at that time instead of speaking (safe local steps only). action=list shows the pending "
        "ones; action=cancel with `id` (a repeating one stops for good). SYRAX fires them itself, also after a restart; "
        "a run missed by hours is skipped, not fired late."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["set", "list", "cancel"]},
            "text": {"type": "string", "description": "what to remind, for set"},
            "at": {"type": "string", "description": "local time for set: HH:MM or YYYY-MM-DDTHH:MM"},
            "in_minutes": {"type": "number", "description": "for set: minutes from now"},
            "repeat": {"type": "string", "enum": list(RULES), "description": "for set: how it repeats"},
            "day": {"type": "string", "description": "monthly: day of month 1-31 or last"},
            "every_minutes": {"type": "number", "description": f"interval: minutes between runs ({MIN_EVERY_MIN}-{MAX_EVERY_MIN})"},
            "between": {"type": "string", "description": "interval: HH:MM-HH:MM window, e.g. 09:00-17:00"},
            "weekdays": {"type": "string", "description": "daily/interval: e.g. mon-fri or sat,sun"},
            "task": {"type": "string", "description": "for set: run this instruction as a SYRAX task instead of speaking"},
            "id": {"type": "string", "description": "reminder id, for cancel"},
        },
        "required": ["action"],
    }
    journal_provider: Callable[[], Journal] = Field(default=get_journal, exclude=True)

    async def execute(self, action: str, text: str = "", at: Optional[str] = None,
                      in_minutes: Optional[float] = None, id: str = "", repeat: str = "", day: Any = None,
                      every_minutes: Optional[float] = None, between: Optional[str] = None, weekdays: Any = None,
                      task: str = "") -> ToolResult:
        journal = self.journal_provider()
        try:
            if action == "set":
                interval = (repeat or "").strip().lower() == "interval"
                due = None if interval and not at and in_minutes in (None, "") else parse_when(at, in_minutes)
                r = await asyncio.to_thread(lambda: create(journal, text, due, None, repeat, day=day, every_min=every_minutes,
                                                           between=between, weekdays=weekdays, task=task))
                return ToolResult(output=f"Reminder {r['id']} set for {when_text(r['due_ts'])}{repeat_text(r) or ' (once)'}: {r['text']}")
            if action == "list":
                rows = await asyncio.to_thread(pending, journal)
                if not rows:
                    return ToolResult(output="No pending reminders.")
                return ToolResult(output="\n".join(f"{r['id']} · {when_text(r['due_ts'])}{repeat_text(r)} · {r['text']}" for r in rows))
            if action == "cancel":
                ok = await asyncio.to_thread(cancel, journal, id)
                return ToolResult(output=f"Reminder {id} cancelled.") if ok else ToolResult(error=f"no pending reminder {id!r}")
            return ToolResult(error="action must be set, list or cancel")
        except ValueError as e:
            return ToolResult(error=f"remind: {e}")
