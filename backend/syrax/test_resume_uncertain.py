"""Live 2026-10-25 (audit): Core.resume started any INTERRUPTED task, also one whose
last operation recovery could not verify (UNCERTAIN: a write, code, a page), and the
web UI offered RESUME on every one of them; the only protection was a note in the
prompt. An UNCERTAIN task now starts only on the human's explicit word (force + note),
journaled as task.resume_forced before the resume; a RESUMABLE task resumes as before."""

import asyncio

from syrax.test_bridge import (  # noqa: F401
    ORIGIN, TestClient, boot, core_mod, drain_until_idle, get_journal, recv_until, reply, script, seed_interrupted, server,
)

APPEND = "open('report.txt', 'a').write('x')"


def uncertain_task():
    """A previous process died inside python_execute: nothing can say whether the append ran."""
    j = get_journal()
    t = j.start_task_sync("count the lines of the report")
    j.record_sync("tool.started", {"id": "e1", "name": "python_execute", "args": {"code": APPEND}, "step": 2}, task_id=t)
    j.record_sync("task.interrupted", {
        "error": "restart",
        "recovery": {"state": "UNCERTAIN", "operation_state": "UNCERTAIN",
                     "operation": {"id": "e1", "name": "python_execute", "args": {"code": APPEND}, "step": 2}},
    }, task_id=t)
    return t


def test_an_uncertain_task_is_not_resumed_without_the_humans_word(script):
    t = uncertain_task()
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert [i["recovery_state"] for i in hello["interrupted"]] == ["UNCERTAIN"]
        ws.send_json({"type": "resume", "task_id": t})
        ws.send_json({"type": "ping"})  # answered once the resume was handled: everything it sent comes first
        _, seen = recv_until(ws, "pong")
    notices = [e for e in seen if e["type"] == "notice"]
    assert len(notices) == 1, seen
    assert "UNCERTAIN" in notices[0]["text"] and "python_execute" in notices[0]["text"] and "force" in notices[0]["text"]
    assert not any(e["type"] == "recovery" for e in seen)
    j = get_journal()
    assert j.task(t)["status"] == "INTERRUPTED"
    assert "recovery.resumed" not in [e["type"] for e in j.events(t)]
    assert script.seen == []  # the brain was never asked


def test_core_resume_says_why_and_what_was_in_flight(script):
    t = uncertain_task()
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    problem = asyncio.run(core.resume(t, session_id=None))
    assert problem and problem.startswith(f"task {t}'s last operation is UNCERTAIN (python_execute") and "force" in problem
    assert not core.busy and core.journal.task(t)["status"] == "INTERRUPTED"


def test_a_forced_resume_is_journaled_with_the_note_then_runs(script):
    t = uncertain_task()
    script.queue = [reply("The report has 37 lines; the append ran once.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "resume", "task_id": t, "force": True, "note": "confirmed in the UI"})
        resumed, seen = recv_until(ws, "recovery")
        assert resumed["event"] == "resumed" and resumed["task_id"] == t
        assert any(e["type"] == "task" and e.get("event") == "resume_forced" and e["task_id"] == t for e in seen)
        drain_until_idle(ws)
    j = get_journal()
    assert j.task(t)["status"] == "SUCCESS"
    events = j.events(t)
    kinds = [e["type"] for e in events]
    assert kinds.index("task.resume_forced") < kinds.index("recovery.resumed") < kinds.index("task.completed")
    forced = [e for e in events if e["type"] == "task.resume_forced"]
    assert len(forced) == 1 and forced[0]["payload"]["note"] == "confirmed in the UI"
    # the model still got the warning about the operation in flight
    assert any("RESUMED AFTER INTERRUPTION" in (getattr(m, "content", "") or "") and "UNCERTAIN" in m.content for m in script.seen[-1])


def test_a_resumable_task_still_resumes_without_force(script, tmp_path):
    t = seed_interrupted(tmp_path)
    script.queue = [reply("Greeting file is there. Done.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert hello["interrupted"][0]["recovery_state"] == "RESUMABLE"
        ws.send_json({"type": "resume", "task_id": t})
        resumed, _ = recv_until(ws, "recovery")
        assert resumed["event"] == "resumed" and resumed["task_id"] == t
        drain_until_idle(ws)
    j = get_journal()
    assert j.task(t)["status"] == "SUCCESS"
    assert "task.resume_forced" not in [e["type"] for e in j.events(t)]
