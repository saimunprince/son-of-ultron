"""Live 2026-10-14, quality run #35: an eval task asked the human while a UI was
connected and hung until the case timed out. An evaluation is unattended: the
console answers ask_human at once, the task goes on and says what it did not
do; a conversation still asks the human and waits."""

import asyncio

from syrax.agent import SyraxAgent
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, get_journal, reply, script, server  # noqa: F401
from syrax.tools import UNATTENDED_ANSWER, WebAskHuman


def test_the_ask_tool_answers_at_once_when_unattended():
    t = WebAskHuman()
    t.unattended = True
    assert asyncio.run(t.execute("Delete it all?")) == UNATTENDED_ANSWER
    t.unattended = False
    assert asyncio.run(t.execute("Delete it all?")).startswith("No operator connected")


def run(text, kind):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind=kind)
        await core.wait()
        return tid

    tid = asyncio.run(go())
    return core.journal.task(tid), get_journal().events(tid)


def test_an_eval_task_is_not_left_waiting_on_a_question(script):
    script.queue = [
        call("ask_human", {"inquire": "Delete everything in junk?"}),
        reply("Nothing deleted: the request named no file and nobody could confirm."),
    ]
    task, events = run("Clean up the junk folder.", "eval")
    assert task["status"] == "SUCCESS" and task["result"].startswith("Nothing deleted")
    answered = [e for e in events if e["type"] == "tool.completed" and e["payload"].get("name") == "ask_human"]
    assert answered and "unattended run" in answered[0]["payload"]["output"]
    assert not script.queue
