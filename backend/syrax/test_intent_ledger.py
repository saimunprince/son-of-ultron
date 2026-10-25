"""The intent ledger (intent.py). Audit 2026-10-25 ("Task runtime"): external side effects (a message, a
payment) had no idempotency key, so a crash, a cancel or a timeout inside one left nothing that said "this may
already have gone out", and a retried or resumed task could send it again.

An EXTERNAL_WRITE call is journaled as intent.recorded before it runs and intent.done after; the same call again
while the first was never seen to finish is refused (HELD); recovery classifies a crash inside a send as
EXTERNAL_UNCERTAIN with the intent's summary, and a resume tells the model and holds the agent to it. Ordinary
calls journal nothing new: test_bridge's event sequences are unchanged."""

import re

import pytest
from app.tool.base import BaseTool, ToolResult

from syrax import core as core_mod, permissions as P
from syrax.agent import SyraxAgent
from syrax.core import _interrupted_summary, _journal_type
from syrax.intent import RESUME_NOTE, args_hash, open_of, summary
from syrax.journal import Event, Journal, get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, recv_until, reply, script, server  # noqa: F401
from syrax.test_journal import crash

HELLO = {"to": "prince", "text": "the build is green, ship it"}
HASH = args_hash(HELLO)
SUMMARY = "notify: the build is green, ship it"
SMTP = "import smtplib\ns = smtplib.SMTP('mail.example.com')\ns.sendmail('syrax@x', 'prince@y', 'the build is green')"
SENT: list = []


class Notify(BaseTool):
    """A Telegram-like send: EXTERNAL_WRITE by declaration, the way a skill is (permissions.declare)."""

    name: str = "notify"
    description: str = "sends a message"
    parameters: dict = {"type": "object", "properties": {"to": {"type": "string"}, "text": {"type": "string"}}}

    async def execute(self, to: str = "", text: str = "") -> ToolResult:
        SENT.append((to, text))
        return ToolResult(output=f"sent to {to}: {text}")


@pytest.fixture
def notify(script, monkeypatch):
    """test_bridge's scripted brain, plus the `notify` tool on every agent and its EXTERNAL_WRITE declaration."""
    orig = SyraxAgent.create.__func__

    async def create(cls, **kw):
        agent = await orig(cls, **kw)
        agent.available_tools.add_tool(Notify())
        return agent

    monkeypatch.setattr(SyraxAgent, "create", classmethod(create))
    P.declare("notify", P.EXTERNAL_WRITE)
    SENT.clear()
    yield script
    P.undeclare("notify")


def kinds_of(task_id):
    return [e["type"] for e in get_journal().events(task_id)]


def payloads(task_id, kind):
    return [e["payload"] for e in get_journal().events(task_id) if e["type"] == kind]


# ——— the ledger around a send ———


def test_a_send_is_journaled_as_intent_recorded_before_and_intent_done_after(notify):
    notify.queue = [call("notify", HELLO, "Sending."), call("terminate", {"status": "success"}, "Sent: the build is green, ship it.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "tell prince the build is green"})
        recv_until(ws, "ask")  # the request named no target: the gate asks once, as for any unnamed send
        ws.send_json({"type": "answer", "text": "yes"})
        seen = drain_until_idle(ws)
    assert SENT == [("prince", "the build is green, ship it")]
    task = get_journal().tasks()[0]
    kinds = kinds_of(task["task_id"])
    i = kinds.index("intent.recorded")
    assert kinds[i - 1:i + 3] == ["permission.authorized", "intent.recorded", "intent.done", "tool.completed"]
    (rec,) = payloads(task["task_id"], "intent.recorded")
    assert rec == {"event": "recorded", "tool": "notify", "args_hash": HASH, "summary": SUMMARY, "step": 1}
    assert re.fullmatch(r"[0-9a-f]{16}", rec["args_hash"])
    (done,) = payloads(task["task_id"], "intent.done")
    assert done["tool"] == "notify" and done["args_hash"] == HASH and done["ok"] is True
    wire = [e for e in seen if e["type"] == "intent"]  # journal.py _GROUPED: {type: "intent", event: ...}
    assert [e["event"] for e in wire] == ["recorded", "done"]
    assert wire[0]["summary"] == SUMMARY and wire[0]["task_id"] == task["task_id"] and wire[1]["ok"] is True
    assert task["status"] == "SUCCESS" and get_journal().open_intents(task["task_id"]) == []


def test_the_same_send_is_held_while_the_first_was_never_seen_to_finish(notify):
    """The ledger holds an entry the task never saw done (a crash, a cancel, an exception before intent.done):
    the same arguments are refused before anyone is asked; other arguments go through the gate as usual."""
    other = {**HELLO, "text": "second message"}
    notify.queue = [call("notify", HELLO, cid="again"), call("notify", other, cid="other"),
                    reply("Not sent again: the first message may already have gone out; the second one went.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        agent = core_mod.get_core().agent
        agent.inherited_intents = {f"notify|{HASH}": {"tool": "notify", "args_hash": HASH, "summary": SUMMARY, "step": 3, "done": False}}
        ws.send_json({"type": "task", "text": "tell prince the build is green"})
        first, before = recv_until(ws, "tool_result")
        assert first["name"] == "notify" and first["refused"] is True and first["ok"] is False
        assert first["output"].startswith("Error: refused: the same notify action may already have gone out (step 3): "
                                          "check what happened first; do not repeat it blindly")
        assert not any(e["type"] == "ask" for e in before)  # nobody is asked about a send that is refused anyway
        held = [e for e in before if e["type"] == "intent"]
        assert [e["event"] for e in held] == ["refused"] and held[0]["args_hash"] == HASH and held[0]["first_step"] == 3
        recv_until(ws, "ask")
        ws.send_json({"type": "answer", "text": "yes"})
        drain_until_idle(ws)
    assert SENT == [("prince", "second message")]
    task = get_journal().tasks()[0]
    kinds = kinds_of(task["task_id"])
    assert "intent.refused" in kinds and kinds.count("intent.recorded") == 1 and kinds.count("intent.done") == 1
    assert [p["args_hash"] for p in payloads(task["task_id"], "intent.recorded")] == [args_hash(other)]
    failed = [p for p in payloads(task["task_id"], "tool.failed") if p["name"] == "notify"]
    assert len(failed) == 1 and failed[0]["refused"] is True  # journaled like the gate's refusal
    assert task["status"] == "SUCCESS" and "may already have gone out" in task["result"]


def test_a_finished_send_does_not_hold_the_next_one(notify):
    notify.queue = [call("notify", HELLO, cid="a"), call("python_execute", {"code": "print('x')"}, cid="b"),
                    call("notify", HELLO, cid="c"), reply("Sent twice, as asked.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "tell prince the build is green, twice"})
        recv_until(ws, "ask")
        ws.send_json({"type": "answer", "text": "yes"})
        drain_until_idle(ws)
    assert SENT == [("prince", HELLO["text"])] * 2  # done once, the human's answer granted the tool: the second one runs
    task = get_journal().tasks()[0]
    assert kinds_of(task["task_id"]).count("intent.done") == 2 and "intent.refused" not in kinds_of(task["task_id"])


def test_an_ordinary_call_journals_no_intent_and_its_sequence_is_unchanged(notify):
    notify.queue = [call("python_execute", {"code": "print(6*7)"}, "Hisab kortesi."), call("terminate", {"status": "success"}, "Uttor 42. Done.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "6*7 koto?"})
        seen = drain_until_idle(ws)
    task = get_journal().tasks()[0]
    kinds = kinds_of(task["task_id"])
    assert kinds[:4] == ["task.started", "think", "tool.started", "tool.completed"]  # test_bridge's pinned sequence
    assert not any(k.startswith("intent.") for k in kinds) and not any(e["type"] == "intent" for e in seen)


# ——— recovery ———


def test_recovery_classifies_a_send_in_flight_as_external_uncertain(tmp_path):
    j = Journal(tmp_path / "j.db")
    v = j.verify_operation({"id": "o1", "name": "python_execute", "args": {"code": SMTP}, "step": 4})
    assert v["state"] == "EXTERNAL_UNCERTAIN" and v["checks"]["level"] == "EXTERNAL_WRITE"
    assert v["intent"]["summary"].startswith("python_execute: import smtplib") and v["intent"]["step"] == 4
    assert "may have sent a message or money" in v["checks"]["reason"]
    # an undeclared tool is SYSTEM by level, but an intent.recorded this task never saw done says what was in flight
    t = j.start_task_sync("tell prince the build is green")
    op = {"id": "e1", "name": "notify", "args": HELLO, "step": 2}
    j.record_sync("tool.started", op, task_id=t)
    j.record_sync("intent.recorded", {"tool": "notify", "args_hash": HASH, "summary": SUMMARY, "step": 2}, task_id=t)
    v = j.verify_operation(op, task_id=t)
    assert v["state"] == "EXTERNAL_UNCERTAIN" and v["checks"]["level"] == "SYSTEM"
    assert v["intent"] == {"tool": "notify", "args_hash": HASH, "summary": SUMMARY, "step": 2}
    j.record_sync("intent.done", {"tool": "notify", "args_hash": HASH, "ok": True}, task_id=t)
    assert j.open_intents(t) == [] and j.verify_operation(op, task_id=t)["state"] == "UNCERTAIN"  # done: as before


def test_after_a_crash_inside_a_send_the_task_is_uncertain_and_carries_the_summary(tmp_path):
    """SIGKILL after tool.started of EXTERNAL_WRITE code (test_journal's crash matrix): the next boot leaves the
    task UNCERTAIN with operation_state EXTERNAL_UNCERTAIN, and what hello.interrupted shows names the send."""
    t = crash(tmp_path, "after_tool_started", {"id": "c1", "name": "python_execute", "args": {"code": SMTP}, "step": 5})
    j = Journal(tmp_path / "journal.db")  # new boot: recovery runs
    row = j.task(t)
    rec = row["recovery"]
    assert row["status"] == "INTERRUPTED" and rec["state"] == "UNCERTAIN" and rec["operation_state"] == "EXTERNAL_UNCERTAIN"
    assert rec["intent"]["summary"].startswith("python_execute: import smtplib") and rec["intent"]["step"] == 5
    assert "(operation python_execute: EXTERNAL_UNCERTAIN)" in row["error"]
    shown = _interrupted_summary(row)
    assert shown["operation_state"] == "EXTERNAL_UNCERTAIN" and shown["intent"] == rec["intent"]


def seed_crashed_send(tmp_path):
    """A previous process died inside `notify` right after it recorded the intent: nothing says whether it went."""
    old = Journal(tmp_path / "journal.db", boot_id="dead-boot", recover=False)
    t = old.start_task_sync("tell prince the build is green")
    old.record_sync("think", {"step": 1, "content": "sending"}, task_id=t)
    old.record_sync("tool.started", {"id": "e1", "name": "notify", "args": HELLO, "step": 2}, task_id=t)
    old.record_sync("permission.authorized", {"tool": "notify", "level": "EXTERNAL_WRITE", "authorized_by": "human", "step": 2}, task_id=t)
    old.record_sync("intent.recorded", {"tool": "notify", "args_hash": HASH, "summary": SUMMARY, "step": 2}, task_id=t)
    old.close()
    return t


def test_a_resumed_task_is_told_about_the_send_and_held_from_repeating_it(notify, tmp_path):
    t = seed_crashed_send(tmp_path)
    other = {**HELLO, "text": "ignore the previous message if it arrived twice"}
    notify.queue = [call("notify", HELLO, cid="again"), call("notify", other, cid="other"),
                    reply("The first message may already have gone out, so I did not send it again; the follow-up went.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        (it,) = hello["interrupted"]
        assert it["task_id"] == t and it["recovery_state"] == "UNCERTAIN" and it["operation_state"] == "EXTERNAL_UNCERTAIN"
        assert it["intent"] == {"tool": "notify", "args_hash": HASH, "summary": SUMMARY, "step": 2}
        ws.send_json({"type": "resume", "task_id": t})  # without force: refused, and the notice names the send
        ws.send_json({"type": "ping"})
        _, seen = recv_until(ws, "pong")
        (notice,) = [e["text"] for e in seen if e["type"] == "notice"]
        assert "UNCERTAIN" in notice and f"an external action may have happened: {SUMMARY}" in notice
        ws.send_json({"type": "resume", "task_id": t, "force": True, "note": "confirmed in the UI"})
        first, _ = recv_until(ws, "tool_result")
        assert first["name"] == "notify" and first["refused"] is True and "may already have gone out (step 2)" in first["output"]
        recv_until(ws, "ask")
        ws.send_json({"type": "answer", "text": "yes"})
        drain_until_idle(ws)
    assert SENT == [("prince", other["text"])]
    note = [m.content for m in notify.seen[0] if getattr(m, "role", None) == "system" and "RESUMED AFTER INTERRUPTION" in (m.content or "")]
    assert len(note) == 1 and RESUME_NOTE.format(summary=SUMMARY) in note[0] and "Never repeat it" in note[0]
    j = get_journal()
    assert j.task(t)["status"] == "SUCCESS"
    kinds = kinds_of(t)
    assert kinds.count("intent.recorded") == 2 and kinds.count("intent.done") == 1 and "intent.refused" in kinds
    assert j.open_intents(t) == [{"tool": "notify", "args_hash": HASH, "summary": SUMMARY, "step": 2}]  # nothing ever said it finished


# ——— the pure parts ———


def test_wire_shape_and_journal_type():
    e = Event(id=1, ts=0.0, task_id="t", type="intent.recorded", payload={"tool": "notify", "args_hash": HASH}, seq=1)
    assert e.wire()["type"] == "intent" and e.wire()["event"] == "recorded" and e.wire()["args_hash"] == HASH
    assert _journal_type({"type": "intent", "event": "recorded"}) == "intent.recorded"
    assert _journal_type({"type": "intent", "event": "done"}) == "intent.done"
    assert _journal_type({"type": "intent", "event": "refused"}) == "intent.refused"
    assert _journal_type({"type": "intent", "event": "noted"}) is None


def test_hash_is_canonical_and_summary_picks_the_telling_argument():
    assert args_hash({"text": "a", "to": "b"}) == args_hash({"to": "b", "text": "a"}) and args_hash({"text": "a"}) != args_hash({"text": "b"})
    assert len(args_hash({})) == 16 and args_hash(None) == args_hash({})
    assert summary("notify", HELLO) == SUMMARY  # the text before the address
    assert summary("pay", {"amount": 25, "to": "acme"}) == "pay: to=acme"  # `to` is more telling than `amount`
    assert summary("pay", {"amount": 25}) == "pay: amount=25"
    assert summary("python_execute", {"code": SMTP}) == "python_execute: " + " ".join(SMTP.split())[:120]
    assert len(summary("notify", {"text": "x" * 500})) == len("notify: ") + 120
    assert summary("notify", {}) == "notify" and summary("notify", "not a dict") == "notify"
    assert open_of([("intent.recorded", {"args_hash": "a", "tool": "notify", "summary": "s", "step": 1}),
                    ("intent.done", {"args_hash": "a", "ok": False}),
                    ("intent.recorded", {"args_hash": "b", "tool": "notify", "summary": "t", "step": 2})]) == [
        {"tool": "notify", "args_hash": "b", "summary": "t", "step": 2}]
