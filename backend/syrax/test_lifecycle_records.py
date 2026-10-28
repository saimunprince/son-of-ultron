"""Mission 2026-10-28: shutdown is bounded and leaves a final-state record (system.shutdown), and "SYRAX committed its
change" and "a restarted SYRAX runs that commit" are different journal facts (commit.created vs release.live)."""

import asyncio

from syrax import core as core_mod
from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, recv_until, script, server  # noqa: F401


def test_shutdown_journals_the_final_state_and_does_not_hang(script, monkeypatch):
    core = core_mod.get_core()

    async def stuck():
        await asyncio.sleep(3600)

    monkeypatch.setattr(core.autonomy, "stop", stuck)  # a step that never ends
    asyncio.run(core.shutdown(timeout=0.2))
    rec = [e["payload"] for e in get_journal().recent_events() if e["type"] == "system.shutdown"]
    assert rec and "autonomy" in rec[-1]["late"] and rec[-1]["queue_held"] is True


def test_release_live_is_recorded_once_and_only_for_syrax_s_own_last_commit(script):
    core = core_mod.get_core()
    j = get_journal()
    loop = asyncio.new_event_loop()
    assert loop.run_until_complete(core.note_running_release("f" * 40)) is None  # no own commit: nothing to note
    j.record_sync("commit.created", {"commit": "a" * 40, "files": ["backend/syrax/x.py"]})
    assert loop.run_until_complete(core.note_running_release("b" * 40)) is None  # running something else
    rec = loop.run_until_complete(core.note_running_release("a" * 40))
    assert rec and rec["commit"] == "a" * 40 and "measured separately" in rec["verified"]
    assert loop.run_until_complete(core.note_running_release("a" * 40)) is None  # once per commit
    assert sum(1 for e in j.recent_events() if e["type"] == "release.live") == 1
