"""Audit 2026-10-29 (lifecycle): Core.emit caught every journal error and only counted it (unjournaled), and _run
decided the status without the count. Two consequences: a task whose steps the journal refused still ended SUCCESS,
and a send whose intent.recorded failed to write went out anyway, so a crash inside it left recovery nothing to say
"this may already have gone out". Now an unjournaled step makes the task PARTIAL, and no intent record means no send."""

from syrax.journal import JournalError, get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, recv_until, reply, script  # noqa: F401
from syrax.test_intent_ledger import HELLO, SENT, kinds_of, notify  # noqa: F401
from syrax import server


def failing(kinds, monkeypatch):
    j = get_journal()
    real = j.record

    async def record(type_, payload=None, task_id=None, **kw):
        if type_ in kinds:
            raise JournalError(f"disk full while writing {type_}")
        return await real(type_, payload, task_id=task_id, **kw)

    monkeypatch.setattr(j, "record", record)


def test_a_send_whose_intent_was_not_journaled_never_goes_out(notify, monkeypatch):
    failing({"intent.recorded"}, monkeypatch)
    notify.queue = [call("notify", HELLO, "Sending."), call("terminate", {"status": "success"}, "Sent.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "tell prince the build is green"})
        recv_until(ws, "ask")
        ws.send_json({"type": "answer", "text": "yes"})
        drain_until_idle(ws)
    assert SENT == []  # nothing left without its record
    task = get_journal().tasks()[0]
    assert task["status"] == "FAILED"
    assert "tool.completed" not in kinds_of(task["task_id"])


def test_a_task_with_a_step_the_journal_refused_is_partial(notify, monkeypatch):
    failing({"think"}, monkeypatch)
    notify.queue = [call("terminate", {"status": "success"}, "All done.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "say done"})
        drain_until_idle(ws)
    task = get_journal().tasks()[0]
    done = [e for e in get_journal().events(task["task_id"]) if e["type"] == "task.completed"][-1]["payload"]
    assert task["status"] == "PARTIAL" and done["reason"] == "unjournaled" and done["unjournaled"] >= 1
