"""Capacity planning: how many days until the disk is full, from its own recent history (EVOLUTION_PLAN direction 279).

The alerts warned only when the disk was already nearly full (under 2 GB). Once a day the free space is kept in the
journal's meta (the last HISTORY_DAYS days); a least-squares line through at least MIN_POINTS days gives the trend, and
when it reaches zero within WARN_DAYS an alert says so, at most once a day. A disk that is not shrinking says nothing."""

from __future__ import annotations

import json
import time
from typing import List, Optional, Tuple

from syrax.journal import Journal

HISTORY_DAYS = 30
MIN_POINTS = 3
WARN_DAYS = 14
META = "disk_history"


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def history(journal: Journal) -> List[Tuple[float, float]]:
    try:
        return [(float(t), float(gb)) for t, gb in json.loads(journal.get_meta(META) or "[]")]
    except (ValueError, TypeError):
        return []


def record(journal: Journal, free_gb: Optional[float], now: Optional[float] = None) -> List[Tuple[float, float]]:
    """Keep today's free space (the first reading of each day) and return the history."""
    now = now or time.time()
    h = history(journal)
    if free_gb is not None and not any(_day(t) == _day(now) for t, _ in h):
        h = (h + [(now, float(free_gb))])[-HISTORY_DAYS:]
        journal.set_meta(META, json.dumps(h))
    return h


def days_until_full(h: List[Tuple[float, float]]) -> Optional[float]:
    """Days from the last reading until free space reaches zero on the least-squares line, or None when there are
    fewer than MIN_POINTS days or the disk is not shrinking."""
    if len(h) < MIN_POINTS:
        return None
    xs = [t / 86400 for t, _ in h]
    ys = [gb for _, gb in h]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var  # GB per day
    if slope >= 0:
        return None
    return round(max(0.0, ys[-1] / -slope), 1)


def check(journal: Journal, free_gb: Optional[float], now: Optional[float] = None) -> Optional[dict]:
    """Record today's reading; an alert {"kind": "disk_trend", "detail"} when the disk is full within WARN_DAYS, once
    a day."""
    now = now or time.time()
    days = days_until_full(record(journal, free_gb, now))
    if days is None or days > WARN_DAYS or journal.get_meta("disk_trend_alerted") == _day(now):
        return None
    journal.set_meta("disk_trend_alerted", _day(now))
    return {"kind": "disk_trend", "detail": f"at the current rate the disk is full in about {days:g} days ({free_gb:g} GB free now)"}
