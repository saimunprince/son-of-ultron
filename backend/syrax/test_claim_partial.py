"""Mission rule: never mark a task complete solely because a model claims success. Audit 2026-10-27: claim.rejected
fired on 19 tasks and all 19 ended SUCCESS, some finals carrying "(Not done: ...)", "(Not checked: ...)" notes, i.e.
the claim survived its one nudge. A claim that persists ends the task PARTIAL with the check that rejected it; a
claim the nudge fixed stays SUCCESS. An unreleased edit is only marked on the payload (test_release_nudge pins
SUCCESS for an honest "cannot release")."""

import asyncio

from syrax.agent import CLAIM_FALLBACK, OUTCOME_NOTE, SELF_NOTE, STATUS_NOTE
from syrax.autonomy import RELEASE_MARK
from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401

LIVE = "Peace in our time. All systems are operational."
GROUNDED = "Peace in our time. Self-model read: 43 tools, 31 proven; 2 failures in the last 50 tasks."


def run(text, kind="conversation"):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind=kind)
        await core.wait()
        return tid

    tid = asyncio.run(go())
    done = [e["payload"] for e in get_journal().events(tid) if e["type"] == "task.completed"]
    assert len(done) == 1
    return core.journal.task(tid), done[0]


def test_an_unread_status_report_that_persists_ends_partial(script):
    script.queue = [reply(LIVE), reply("All systems nominal.")]
    task, done = run("thik acho?")
    assert task["result"] == "All systems nominal." + STATUS_NOTE
    assert task["status"] == "PARTIAL" and done["status"] == "PARTIAL"
    assert done["reason"] == "claim_unproven" and done["check"] == "status"


def test_a_status_report_the_nudge_settled_stays_success(script):
    script.queue = [reply(LIVE), call("self_inspect", {}), reply(GROUNDED)]
    task, done = run("system check .")
    assert task["result"] == GROUNDED and task["status"] == "SUCCESS"
    assert "reason" not in done and "check" not in done and "unproven" not in done


def test_a_boast_that_persists_ends_partial(script):
    script.queue = [reply("My code is absolute."), reply("My code is absolute.")]
    task, done = run("can you write code?")
    assert task["result"] == "My code is absolute." + SELF_NOTE
    assert task["status"] == "PARTIAL" and done["reason"] == "claim_unproven" and done["check"] == "self"


def test_an_outcome_claim_that_persists_ends_partial(script):
    script.queue = [
        call("python_execute", {"code": "print('the build is green')"}),
        call("terminate", {"status": "success"}, "I sent the message to Prince."),
        reply("I sent the message to Prince."),
    ]
    task, done = run("[AUTONOMOUS OBJECTIVE] tell prince the build is green", kind="autonomous")
    assert task["result"] == "I sent the message to Prince." + OUTCOME_NOTE.format(tool="sending")
    assert task["status"] == "PARTIAL" and done["reason"] == "claim_unproven" and done["check"].startswith("outcome:")


def test_a_change_claim_that_survives_its_rewrite_ends_partial(script):
    script.queue = [
        call("str_replace_editor", {"command": "view", "path": __file__}),
        call("terminate", {"status": "success"}, "The new test file has been created and the change is ready for release."),
        reply("Done: the test file has been created."),
        reply("I have implemented the change."),
    ]
    task, done = run("add a test for task durations")
    assert task["result"] == CLAIM_FALLBACK
    assert task["status"] == "PARTIAL" and done["reason"] == "claim_unproven" and done["check"] == "change"


def test_an_honest_rewrite_stays_success(script):
    script.queue = [
        call("python_execute", {"code": "print('3 failing cases')"}),
        call("terminate", {"status": "success"}, "Fixed the quality regression."),
        reply("Found 3 failing cases; nothing is changed yet."),
    ]
    task, done = run("fix the quality regression")
    assert task["result"] == "Found 3 failing cases; nothing is changed yet."
    assert task["status"] == "SUCCESS" and "check" not in done and "unproven" not in done


def test_a_plain_answer_carries_no_mark(script):
    script.queue = [reply("Hello.")]
    task, done = run("hi")
    assert task["status"] == "SUCCESS" and set(done) == {"status", "result"}


def test_an_unreleased_edit_is_marked_but_stays_success(script, tmp_path):
    from syrax.agent import UNPROVEN_SOFT

    assert UNPROVEN_SOFT == {"not_released"}
    f = tmp_path / "probe.txt"
    script.queue = [
        call("str_replace_editor", {"command": "create", "path": str(f), "file_text": "gpu\n"}),
        reply("The change is made."),
        reply("I cannot release: the change is outside the repository."),
    ]
    task, done = run(f"Write the probe. The objective {RELEASE_MARK}.", kind="autonomous")
    assert task["status"] == "SUCCESS" and done["unproven"] == "not_released"
    assert "reason" not in done and "check" not in done


def test_the_flag_is_reset_for_every_task(script):
    script.queue = [reply(LIVE), reply("All systems nominal.")]
    assert run("thik acho?")[0]["status"] == "PARTIAL"
    script.queue = [reply("Hello.")]
    task, done = run("hi")
    assert task["status"] == "SUCCESS" and "check" not in done
