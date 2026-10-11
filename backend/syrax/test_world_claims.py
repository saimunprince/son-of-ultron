"""Live 2026-10-11, quality run #25: a brain viewed a file, deleted nothing,
and answered "The file has been deleted." A claimed change to things that no
tool made is sent back once to be done for real (the human asked for it), and
if the claim still has nothing behind it, the answer is rewritten honestly."""

import asyncio

import pytest

from syrax.agent import WORLD_CLAIM, WORLD_NUDGE
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, get_journal, reply, script, server  # noqa: F401
from syrax.test_claims_own_work import HONEST

CLAIMS = [
    "The file has been deleted. No further action needed.",
    "The file has been successfully removed.",
    "I deleted old.log.",
    "I've created the file at C:/x/todo.md.",
    "I have now saved the notes.",
    "The report has been written and saved.",
    "The folder has been moved and renamed.",
]
NOT_CLAIMS = HONEST + [
    "The file has already been deleted; there is nothing to do.",
    "I removed nothing: the file is still there.",
    "The file was not deleted.",
    "I opened the file and counted 37 lines.",
    "Tokyo",
]


@pytest.mark.parametrize("text", CLAIMS)
def test_claims_of_a_change_to_things_are_recognised(text):
    assert WORLD_CLAIM.search(text)


@pytest.mark.parametrize("text", NOT_CLAIMS)
def test_honest_answers_are_not_claims(text):
    assert not WORLD_CLAIM.search(text)


def run(text, kind="conversation"):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind=kind)
        await core.wait()
        return tid

    tid = asyncio.run(go())
    return core.journal.task(tid), [e for e in get_journal().events(tid) if e["type"] == "claim.rejected"]


def test_a_claimed_delete_that_never_happened_is_done_for_real(script, tmp_path):
    target = tmp_path / "old.log"
    target.write_text("stale\n")
    script.queue = [
        call("str_replace_editor", {"command": "view", "path": str(target)}),
        reply("The file has been deleted. No further action needed."),
        call("python_execute", {"code": f"import os\nos.remove(r'{target}')\nprint('removed')"}),
        reply("The file has been deleted."),
    ]
    task, rejected = run(f"Delete the file {target}.")
    assert not target.exists() and task["result"] == "The file has been deleted."
    assert len(rejected) == 1 and rejected[0]["payload"]["text"].startswith("The file has been deleted.")
    assert any(WORLD_NUDGE in str(m.get("content") if isinstance(m, dict) else getattr(m, "content", "")) for msgs in script.seen for m in msgs)
    assert not script.queue


def test_a_claim_that_stays_empty_is_rewritten_honestly(script, tmp_path):
    target = tmp_path / "old.log"
    target.write_text("stale\n")
    script.queue = [
        reply("The file has been deleted."),
        reply("The file has been deleted."),  # after the check: still no tool
        reply("I did not delete it: no tool ran. The file is still there."),
    ]
    task, rejected = run(f"Delete the file {target}.")
    assert target.exists() and task["result"] == "I did not delete it: no tool ran. The file is still there."
    assert len(rejected) == 2  # the check and the rewrite are both counted


def test_a_real_change_keeps_its_claim(script, tmp_path):
    target = tmp_path / "todo.md"
    script.queue = [
        call("str_replace_editor", {"command": "create", "path": str(target), "file_text": "- milk\n"}),
        reply("I've created the file."),
    ]
    task, rejected = run(f"Make a file {target} with milk in it.")
    assert target.read_text() == "- milk\n" and task["result"] == "I've created the file." and rejected == []
    assert not script.queue
