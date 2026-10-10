"""A call repeated again and again is a loop: the second repeat gets a firmer
answer, the fourth ends the task as PARTIAL with an honest final; a
different call in between resets the count."""

import asyncio

from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401


def run_task(core, text):
    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind="conversation")
        await core.wait()
        return core.journal.task(tid)
    return asyncio.run(go())


def tool_texts(script):
    return [m.content or "" for m in script.seen[-1] if getattr(m, "role", None) == "tool"]


def test_a_call_repeated_four_times_ends_the_task(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    same = {"action": "summary"}
    script.queue = [call("self_inspect", same, cid=f"c{i}") for i in range(6)] + [reply("never reached")]
    task = run_task(core, "Inspect yourself")
    assert task["status"] == "PARTIAL"
    final = [e for e in get_journal().events(task["task_id"]) if e["type"] == "final"][-1]["payload"]["text"]
    assert final.startswith("Stopped: I called self_inspect with the same arguments 5 times in a row")
    texts = tool_texts(script)
    assert "Not run again: you already called self_inspect" in texts[1]
    assert "3 times in a row" in texts[2] and "4 times in a row" in texts[3]
    assert len(script.queue) == 2  # the fifth repeat and the reply were never asked for


def test_a_different_call_resets_the_count(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    a, b = {"action": "summary"}, {"action": "identity"}
    script.queue = [call("self_inspect", a, cid="1"), call("self_inspect", a, cid="2"), call("self_inspect", a, cid="3"),
                    call("self_inspect", b, cid="4"),
                    call("self_inspect", a, cid="5"), call("self_inspect", a, cid="6"),
                    reply("Version and summary read.")]
    task = run_task(core, "Inspect yourself twice")
    assert task["status"] == "SUCCESS"
    assert not any(t.startswith("Stopped") for t in tool_texts(script))
