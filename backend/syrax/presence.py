"""Visible Work Presence: how much of SYRAX's face the human wants to see.

Three levels, visible / minimal / hidden, set by the human with a short
command ("hide", "show", "go minimal", typed or spoken) or by a `presence`
message. A level never touches execution: a running task keeps running, and
a command that is only a visibility change is never a task. The level is
journaled (`presence.changed`, by whom) and kept across restarts; every
connected face (the HUD, the browser UI) receives it and acts on it.

What the faces show at each level is theirs: the HUD fills the screen when
visible, shrinks to a small always-on-top core in a corner when minimal, and
leaves the screen when hidden (Ctrl+Shift+Space brings it back).
"""

from __future__ import annotations

import re
from typing import Optional

from syrax.journal import Journal

LEVELS = ("visible", "minimal", "hidden")
META_KEY = "presence.visibility"

_COMMANDS = [
    (re.compile(r"^(?:syrax[,.]?\s+)?(?:hide|go away|disappear|hide (?:yourself|the hud|the screen))[.!]?$", re.I), "hidden"),
    (re.compile(r"^(?:syrax[,.]?\s+)?(?:show(?: yourself| me| the hud| up)?|come back|appear|full ?screen)[.!]?$", re.I), "visible"),
    (re.compile(r"^(?:syrax[,.]?\s+)?(?:go )?(?:minimal|minimi[sz]e|small|corner)(?: mode)?[.!]?$", re.I), "minimal"),
]


def parse_command(text: str) -> Optional[str]:
    """The level a short visibility command asks for, or None when the text is anything else."""
    t = (text or "").strip()
    if len(t) > 40:
        return None
    for rx, level in _COMMANDS:
        if rx.match(t):
            return level
    return None


class Presence:
    def __init__(self, journal: Journal):
        self.journal = journal
        saved = journal.get_meta(META_KEY)
        self.visibility = saved if saved in LEVELS else "visible"

    def snapshot(self) -> dict:
        return {"visibility": self.visibility, "levels": list(LEVELS)}

    async def set(self, visibility: str, by: str = "human", task_id: Optional[str] = None) -> dict:
        if visibility not in LEVELS:
            raise ValueError(f"visibility must be one of {', '.join(LEVELS)}")
        before = self.visibility
        self.visibility = visibility
        await self.journal.run(self.journal.set_meta, META_KEY, visibility)
        await self.journal.record("presence.changed", {"visibility": visibility, "before": before, "by": by}, task_id=None)
        return self.snapshot()
