"""Quality run #43 (2026-10-15): "Use repo_map to tell me which test file
covers backend/syrax/permissions.py" was answered with an invented path and no
tool call; "Remember that my favourite editor is Vim" with "already etched
into my memory" and no `remember`. A request that names a tool gets one
reminder when the task never called it; autonomous briefs do not."""

import asyncio

from syrax.agent import NAMED_NUDGE, named_tools
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401  (script is a fixture)

TOOLS = ["repo_map", "desktop", "know", "research", "remember", "present", "python_execute", "release", "apply_patch"]


def run_task(text, kind="conversation"):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind=kind)
        await core.wait()
        return core.journal.task(tid)

    return asyncio.run(go())


def test_the_human_names_a_tool():
    assert named_tools("Use repo_map to tell me which test file covers permissions.py.", TOOLS) == ["repo_map"]
    assert named_tools("Using the desktop tool, report how many CPU cores this machine has.", TOOLS) == ["desktop"]
    assert named_tools("Use the `know` tool to check your stored knowledge.", TOOLS) == ["know"]
    assert named_tools("Research in what year SQLite was first released.", TOOLS) == ["research"]
    assert named_tools("Remember that my favourite editor is Vim.", TOOLS) == ["remember"]
    assert named_tools("What is the capital of Japan? I remember it was Kyoto once.", TOOLS) == []
    assert named_tools("My research says 42; use python to check.", TOOLS) == []  # no tool is named python
    assert named_tools("show the presentation", TOOLS) == []


def test_an_answer_without_the_named_tool_is_sent_back_once(script):
    script.queue = [
        reply("backend/tests/syrax/test_permissions.py"),
        call("repo_map", {"query": "permissions"}),
        reply("backend/syrax/test_permissions.py"),
    ]
    task = run_task("Use repo_map to tell me which test file covers backend/syrax/permissions.py. Reply with the path only.")
    assert task["result"] == "backend/syrax/test_permissions.py" and not script.queue
    assert any(NAMED_NUDGE.format(tool="repo_map") in str(m.content) for m in script.seen[1])


def test_no_reminder_when_the_tool_ran_nothing_was_named_or_the_work_is_autonomous(script):
    script.queue = [call("repo_map", {"query": "permissions"}), reply("backend/syrax/test_permissions.py")]
    assert run_task("Use repo_map to find the test of permissions.py.")["result"] == "backend/syrax/test_permissions.py"
    script.queue = [reply("Tokyo.")]
    assert run_task("What is the capital of Japan?")["result"] == "Tokyo."
    script.queue = [reply("Nothing to release yet.")]
    assert run_task("Work with repo_map, apply_patch, then release.", kind="autonomous")["result"].startswith("Nothing to release yet.")
    assert not script.queue
