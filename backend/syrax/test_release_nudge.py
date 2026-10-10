"""A task whose brief asks for a release and that changed files is not let go
without `release`: it is asked once (live: objective 105 finished its change
and its tests, then ended without releasing, and the work was rolled back)."""

import asyncio

from syrax.agent import RELEASE_NUDGE
from syrax.autonomy import BRIEF_HINTS, RELEASE_MARK
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401


def run_task(core, text, kind="autonomous"):
    async def go():
        tid = await core.submit(text, said="the objective", session_id=None, kind=kind)
        await core.wait()
        return core.journal.task(tid)
    return asyncio.run(go())


def user_texts(script):
    return [m.content or "" for m in script.seen[-1] if getattr(m, "role", None) == "user"]


def test_the_release_brief_carries_the_mark():
    assert RELEASE_MARK in BRIEF_HINTS["change_released"]


def test_changed_files_without_release_are_asked_about_once(script, tmp_path):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    f = tmp_path / "probe.txt"
    script.queue = [
        call("str_replace_editor", {"command": "create", "path": str(f), "file_text": "gpu\n"}),
        reply("The change is made."),  # ends without release
        reply("I cannot release: the change is outside the repository."),  # the answer to the one nudge
    ]
    task = run_task(core, f"Write the probe. The objective {RELEASE_MARK}.")
    assert f.exists() and task["status"] == "SUCCESS"
    assert sum(RELEASE_NUDGE in t for t in user_texts(script)) == 1
    assert script.queue == []
    assert task["result"].startswith("I cannot release")


def test_no_mark_or_no_change_means_no_nudge(script, tmp_path):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    f = tmp_path / "note.txt"
    script.queue = [call("str_replace_editor", {"command": "create", "path": str(f), "file_text": "x\n"}), reply("Written."), reply("unused")]
    run_task(core, "Write a note.", kind="conversation")
    assert not any(RELEASE_NUDGE in t for t in user_texts(script)) and script.queue == [reply("unused")]
    script.queue = [reply("Nothing to change."), reply("unused")]
    run_task(core, f"Look only. The objective {RELEASE_MARK}.")
    assert not any(RELEASE_NUDGE in t for t in user_texts(script)) and len(script.queue) == 1
