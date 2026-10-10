"""SYRAX's own work does not leak into the human's conversation: after an
autonomous task, the human's next message continues the human's context, not
the task's (live 2026-10-10: "hi" after an autonomous GPU task made SYRAX
continue editing sysinfo.py)."""

import asyncio

from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401

BRIEF = "[AUTONOMOUS OBJECTIVE] Fix the GPU probe in sysinfo.py and release it."


def submit(core, text, kind):
    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind=kind)
        await core.wait()
        return core.journal.task(tid)
    return asyncio.run(go())


def sent_text(script):
    return " ".join(str(getattr(m, "content", "") or "") for m in script.seen[-1])


def test_the_human_conversation_survives_autonomous_work(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    script.queue = [reply("Nice to meet you, Prince.")]
    submit(core, "My name is Prince and I like short answers.", "conversation")
    script.queue = [call("self_inspect", {"action": "summary"}), reply("Probe looked at.")]
    submit(core, BRIEF, "autonomous")
    script.queue = [reply("Hi Prince.")]
    task = submit(core, "hi", "conversation")
    seen = sent_text(script)
    assert "My name is Prince" in seen  # the human's context is back
    assert "AUTONOMOUS OBJECTIVE" not in seen and "Probe looked at" not in seen  # SYRAX's own work is not
    assert task["result"] == "Hi Prince."


def test_reset_drops_the_kept_conversation(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    script.queue = [reply("Noted.")]
    submit(core, "Remember the word banana.", "conversation")
    script.queue = [reply("Own work done.")]
    submit(core, BRIEF, "autonomous")
    asyncio.run(core.reset())
    script.queue = [reply("Hello.")]
    submit(core, "hi", "conversation")
    assert "banana" not in sent_text(script)
