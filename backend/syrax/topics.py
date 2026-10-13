"""Watched topics: SYRAX checks the news on what the human asked it to watch,
once a day, and says only what is new.

Kept in the journal: topic.watched / topic.unwatched (the list) and
topic.news {topic, items} (what was reported, so a story is never reported
twice). The autonomy cycle runs the check when it is idle (SYRAX_FEATURES=1),
at most once a day per topic; the UI shows and speaks it, and the daily
briefing lists it. The human adds and removes topics with the `watch_topic`
tool ("watch AI chips for me").

From the feature catalog (topic_monitor, morning_briefing); the idea came from
the surveyed JARVIS assistants, the code is SYRAX's own.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import Field

from app.tool.base import BaseTool, ToolResult
from syrax.journal import Journal, get_journal

EVERY_S = 86400.0
MAX_TOPICS = 10
MAX_ITEMS = 5
CHECKED = "topic_checked:"


def _norm(topic: str) -> str:
    return " ".join(str(topic or "").split())[:80]


def watched(journal: Journal) -> List[str]:
    """The watched topics, in the human's spelling, oldest first."""
    events = sorted(journal.events_of_type("topic.watched", limit=2000) + journal.events_of_type("topic.unwatched", limit=2000),
                    key=lambda e: e["id"])
    names: Dict[str, str] = {}
    for e in events:
        t = _norm(e["payload"].get("topic"))
        if e["type"] == "topic.watched":
            names[t.lower()] = t
        else:
            names.pop(t.lower(), None)
    return list(names.values())


def watch(journal: Journal, topic: str) -> str:
    t = _norm(topic)
    if len(t) < 2:
        raise ValueError("say what to watch, e.g. 'AI chips' or 'Bangladesh cricket'")
    current = watched(journal)
    if t.lower() in (x.lower() for x in current):
        return t
    if len(current) >= MAX_TOPICS:
        raise ValueError(f"already watching {MAX_TOPICS} topics; remove one first")
    journal.record_sync("topic.watched", {"topic": t})
    return t


def unwatch(journal: Journal, topic: str) -> bool:
    t = _norm(topic)
    if t.lower() not in (x.lower() for x in watched(journal)):
        return False
    journal.record_sync("topic.unwatched", {"topic": t})
    return True


def reported_urls(journal: Journal, topic: str) -> set:
    return {i.get("url") for e in journal.events_of_type("topic.news", limit=2000)
            if _norm(e["payload"].get("topic")).lower() == topic.lower() for i in e["payload"].get("items") or []}


def due(journal: Journal, now: Optional[float] = None) -> List[str]:
    now = now or time.time()
    out = []
    for t in watched(journal):
        try:
            last = float(journal.get_meta(CHECKED + t.lower()) or 0)
        except ValueError:
            last = 0.0
        if now - last >= EVERY_S:
            out.append(t)
    return out


def fetch_news(topic: str, n: int = MAX_ITEMS * 2) -> List[Dict[str, str]]:
    from ddgs import DDGS

    out = []
    for item in DDGS().news(topic, max_results=n) or []:
        url = item.get("url") or item.get("href")
        if url:
            out.append({"title": str(item.get("title") or "")[:160], "url": url,
                        "source": str(item.get("source") or "")[:60], "date": str(item.get("date") or "")[:25]})
    return out


async def check(journal: Journal, fetch: Optional[Callable[[str], List[Dict[str, str]]]] = None,
                now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Look up every due topic once; journal the new stories (topic.news) and when each was checked."""
    now = now or time.time()
    found = []
    for t in await asyncio.to_thread(due, journal, now):  # journal calls off the event loop
        try:
            items = await asyncio.to_thread(fetch or fetch_news, t)
        except Exception:
            continue  # offline or rate-limited: try again at the next idle cycle
        await asyncio.to_thread(journal.set_meta, CHECKED + t.lower(), str(now))
        seen = await asyncio.to_thread(reported_urls, journal, t)
        new = [i for i in items if i.get("url") not in seen][:MAX_ITEMS]
        if new:
            await journal.record("topic.news", {"topic": t, "items": new})  # fans out: the UI shows and speaks it
            found.append({"topic": t, "items": new})
    return found


def briefing_lines(journal: Journal, since: float) -> List[str]:
    out = []
    for e in journal.events_of_type("topic.news", since=since, limit=200):
        p = e["payload"]
        heads = "; ".join(f"{i.get('title')} ({i.get('source') or 'web'})" for i in (p.get("items") or [])[:3])
        out.append(f"    {p.get('topic')}: {heads}")
    return out


class WatchTopicTool(BaseTool):
    name: str = "watch_topic"
    description: str = (
        "Topics the human wants SYRAX to watch in the news. action=add with `topic` ('AI chips', 'Bangladesh cricket'), "
        "action=list, action=remove with `topic`. Once a day SYRAX looks up each topic and reports only new stories "
        "(a notice, a spoken line and the daily briefing)."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "list", "remove"]},
            "topic": {"type": "string", "description": "the topic, for add and remove"},
        },
        "required": ["action"],
    }
    journal_provider: Callable[[], Journal] = Field(default=get_journal, exclude=True)

    async def execute(self, action: str, topic: str = "") -> ToolResult:
        journal = self.journal_provider()
        try:
            if action == "add":
                t = await asyncio.to_thread(watch, journal, topic)
                return ToolResult(output=f"Watching '{t}'. New stories are reported once a day.")
            if action == "list":
                rows = await asyncio.to_thread(watched, journal)
                return ToolResult(output="Watching: " + ", ".join(rows) if rows else "No topics watched.")
            if action == "remove":
                ok = await asyncio.to_thread(unwatch, journal, topic)
                return ToolResult(output=f"No longer watching '{topic}'.") if ok else ToolResult(error=f"not watching {topic!r}")
            return ToolResult(error="action must be add, list or remove")
        except ValueError as e:
            return ToolResult(error=f"watch_topic: {e}")
