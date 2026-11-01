"""Audit 2026-11-01 (integrations I-03): core.broadcast awaited every observer in turn with no bound, so one client
that stopped reading held all fan-out and the running task. A client that takes longer than OBSERVER_TIMEOUT_S is
dropped; the others still get the event."""

import asyncio

from syrax import core as core_mod
from syrax.journal import Journal


def test_a_stuck_observer_is_dropped_and_the_others_still_get_the_event(tmp_path, monkeypatch):
    monkeypatch.setattr(core_mod, "OBSERVER_TIMEOUT_S", 0.2)
    c = core_mod.Core(Journal(tmp_path / "j.db"))
    got = []

    async def stuck(event):
        await asyncio.sleep(30)

    async def fine(event):
        got.append(event["type"])

    c.subscribe(stuck)
    c.subscribe(fine)

    async def go():
        await asyncio.wait_for(c.broadcast({"type": "notice", "text": "x"}), 5)
        await c.broadcast({"type": "notice", "text": "y"})

    asyncio.run(go())
    assert got == ["notice", "notice"] and stuck not in c.observers and fine in c.observers
