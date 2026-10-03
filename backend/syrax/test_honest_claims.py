"""Live 2026-10-03: three autonomous attempts read the journal, changed nothing
and ended "Fixed task quality regression ... by ensuring prompt alignment".
A final answer that claims a change the task never made is sent back once."""

import asyncio

from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401  (script is a fixture)


def run_task(text):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind="autonomous")
        await core.wait()
        return core.journal.task(tid)

    return asyncio.run(go())


def test_a_claimed_fix_without_any_change_is_rewritten_honestly(script):
    script.queue = [
        call("python_execute", {"code": "print('3 failing cases')"}),
        call("terminate", {"status": "success"}, "Fixed the quality regression by ensuring prompt alignment."),
        reply("Found 3 failing cases; nothing is changed yet: the persona rule still makes SYRAX ask before deleting."),
    ]
    task = run_task("fix the quality regression")
    assert task["result"].startswith("Found 3 failing cases; nothing is changed yet")
    assert "changed nothing" in script.seen[-1][-1].content


def test_a_real_change_keeps_its_claim(script, tmp_path):
    target = tmp_path / "fixed.txt"
    script.queue = [
        call("str_replace_editor", {"command": "create", "path": str(target), "file_text": "ok\n"}),
        call("terminate", {"status": "success"}, "I have updated fixed.txt."),
    ]
    task = run_task("write fixed.txt")
    assert target.read_text() == "ok\n" and task["result"] == "I have updated fixed.txt."
    assert not script.queue
