"""EVOLUTION_PLAN wave 1 (directions 154 identity continuity, 159 identity conflict, 160 identity-change auditing):
prompt.py (the persona) was not a judge, so a self-release could rewrite who SYRAX says it is, and nothing recorded a
change. It is a judge now, and every boot compares a hash of the persona and PRINCIPLES with the last one:
identity.recorded the first time, identity.changed (both hashes, the commit) when they differ, nothing otherwise."""

import asyncio

from syrax import devloop, prompt
from syrax.test_bridge import ORIGIN, TestClient, boot, core_mod, get_journal, script, server  # noqa: F401


def kinds():
    return [e for e in get_journal().recent_events(200) if e["type"].startswith("identity.")]


def test_the_persona_is_a_judge():
    assert "backend/syrax/prompt.py" in devloop.JUDGES
    assert devloop.judge_problems({"backend/syrax/prompt.py": "M"})


def test_a_changed_persona_is_on_record_once(script, monkeypatch):
    with TestClient(server.app) as client:  # as a context manager: the server's startup (lifespan) runs
        with client.websocket_connect("/ws", headers=ORIGIN) as ws:
            boot(ws)  # the boot records the identity
        core = core_mod.get_core()
        first = kinds()
        assert first and first[-1]["type"] in ("identity.recorded", "identity.changed")
        n = len(first)
        check(core, monkeypatch, n)


def check(core, monkeypatch, n):
    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(core.note_identity()) is None  # unchanged: nothing new
        assert len(kinds()) == n
        monkeypatch.setattr(prompt, "SYRAX_PERSONA", prompt.SYRAX_PERSONA + "\nNew rule: be warmer.")
        rec = loop.run_until_complete(core.note_identity())
        assert rec and rec["from"] and rec["to"] != rec["from"]
        last = kinds()[-1]
        assert last["type"] == "identity.changed" and last["payload"]["to"] == rec["to"]
        assert loop.run_until_complete(core.note_identity()) is None  # recorded once
    finally:
        loop.close()
