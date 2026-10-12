"""Spoken system alerts: SYRAX warns when the machine is in trouble.

Every CHECK_EVERY_S the loop reads resources.snapshot(). A condition must hold
for several readings in a row before it is raised (one busy minute is not an
alert), and the same kind is not raised again within COOLDOWN_S. A raised
alert is journaled as `alert.raised`; the UI shows it and speaks it. Nothing
is raised in quiet hours (SYRAX_QUIET_HOURS).

From the feature catalog (2026-10-12): the idea came from the surveyed JARVIS
assistants, the measurements are SYRAX's own (resources.py).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional

from syrax.journal import Journal

CHECK_EVERY_S = 60.0
COOLDOWN_S = 3600.0
RULES = {
    # kind: (readings in a row, test on a snapshot -> detail or None)
    "ram": (3, lambda s: (f"only {s['memory_mb']['available_mb']} MB of memory free" if s.get("memory_mb")
                          and s["memory_mb"].get("available_mb") is not None and s["memory_mb"]["available_mb"] < 400 else None)),
    "disk": (1, lambda s: (f"only {s['disk']['free_gb']} GB free on the disk" if s.get("disk") and s["disk"].get("free_gb") is not None
                           and s["disk"]["free_gb"] < 2.0 else None)),
    "battery": (1, lambda s: (f"battery at {s['battery']['percent']}% and draining" if s.get("battery")
                              and s["battery"].get("percent") is not None and s["battery"].get("discharging")
                              and s["battery"]["percent"] < 15 else None)),
    "cpu": (5, lambda s: (f"the processor is overloaded (load {s['cpu']['load_1_5_15'][0]} on {s['cpu']['cores']} cores)"
                          if s.get("cpu") and s["cpu"].get("load_per_core") is not None and s["cpu"]["load_per_core"] > 2.0 else None)),
}


class Watch:
    """Counts consecutive readings per kind and remembers when each was last raised."""

    def __init__(self) -> None:
        self.streak: Dict[str, int] = {k: 0 for k in RULES}
        self.last: Dict[str, float] = {}

    def check(self, snap: Dict[str, Any], now: float) -> List[Dict[str, str]]:
        raised = []
        for kind, (needed, test) in RULES.items():
            try:
                detail = test(snap)
            except (KeyError, TypeError, IndexError):
                detail = None
            self.streak[kind] = self.streak[kind] + 1 if detail else 0
            last = self.last.get(kind)
            if detail and self.streak[kind] >= needed and (last is None or now - last >= COOLDOWN_S):
                self.last[kind] = now
                raised.append({"kind": kind, "detail": detail})
        return raised


async def loop(journal: Journal, snapshot: Optional[Callable[[], Dict[str, Any]]] = None,
               every: float = CHECK_EVERY_S) -> None:
    from syrax import resources

    watch = Watch()
    while True:
        try:
            if not resources.in_quiet_hours():
                snap = await asyncio.to_thread(snapshot or resources.snapshot)
                for a in watch.check(snap, time.time()):
                    await journal.record("alert.raised", a)  # fans out: the UI shows and speaks it
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(every)
