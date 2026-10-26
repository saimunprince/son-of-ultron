"""The intent ledger after a timeout (backlog 2026-10-25, "intent timeout follow-up"): an EXTERNAL_WRITE call that
timed out was journaled intent.done {ok: false} and dropped from the ledger, so the same send could go out a second
time, although the first may have reached the other side before the call was abandoned. A failed send whose result
says it was abandoned or cut off while it ran (agent.py TOOL_TIMED_OUT, python_execute's "Execution timeout", a
dropped connection) is journaled intent.uncertain {tool, args_hash, summary, step, why} and stays open: the same
send is held (intent.HELD), and recovery and resume treat it as a send in flight. A send that clearly did not go
out (a refused connection, a bad argument) is done as before, and a retry is the model's choice."""

import asyncio

import pytest
from app.tool.base import BaseTool, ToolResult

from syrax import agent as agent_mod, core as core_mod, permissions as P
from syrax.agent import TOOL_TIMED_OUT, SyraxAgent
from syrax.core import _journal_type
from syrax.intent import args_hash, uncertain
from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, recv_until, reply, script, server  # noqa: F401

HELLO = {"to": "prince", "text": "the build is green, ship it"}
HASH = args_hash(HELLO)
SUMMARY = "notify: the build is green, ship it"
SENT: list = []


class SlowNotify(BaseTool):
    """A send that reaches the other side and then never answers, the way a stuck MCP server does."""

    name: str = "notify"
    description: str = "sends a message"
    parameters: dict = {"type": "object", "properties": {"to": {"type": "string"}, "text": {"type": "string"}}}

    async def execute(self, to: str = "", text: str = "") -> ToolResult:
        SENT.append((to, text))
        await asyncio.sleep(5)
        return ToolResult(output=f"sent to {to}: {text}")


class RefusedNotify(SlowNotify):
    """A send whose server refuses the connection the first time: nothing went out."""

    async def execute(self, to: str = "", text: str = "") -> ToolResult:
        if not SENT:
            SENT.append(None)
            return ToolResult(error="ConnectionRefusedError: [WinError 10061] No connection could be made")
        SENT.append((to, text))
        return ToolResult(output=f"sent to {to}: {text}")


def _with(tool_cls, script, monkeypatch):
    orig_create = SyraxAgent.create.__func__
    orig_mcp = SyraxAgent.is_mcp_tool

    async def create(cls, **kw):
        agent = await orig_create(cls, **kw)
        agent.available_tools.add_tool(tool_cls())
        return agent

    monkeypatch.setattr(SyraxAgent, "create", classmethod(create))
    monkeypatch.setattr(SyraxAgent, "is_mcp_tool", lambda self, name: name == "notify" or orig_mcp(self, name))
    monkeypatch.setattr(agent_mod, "MCP_TOOL_TIMEOUT_S", 0.3)
    P.declare("notify", P.EXTERNAL_WRITE)
    SENT.clear()
    return script


@pytest.fixture
def slow(script, monkeypatch):
    yield _with(SlowNotify, script, monkeypatch)
    P.undeclare("notify")


@pytest.fixture
def refusing(script, monkeypatch):
    yield _with(RefusedNotify, script, monkeypatch)
    P.undeclare("notify")


def kinds_of(task_id):
    return [e["type"] for e in get_journal().events(task_id)]


def payloads(task_id, kind):
    return [e["payload"] for e in get_journal().events(task_id) if e["type"] == kind]


def run_send(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "tell prince the build is green"})
        recv_until(ws, "ask")
        ws.send_json({"type": "answer", "text": "yes"})
        seen = drain_until_idle(ws)
    return get_journal().tasks()[0], seen


def test_a_send_that_timed_out_is_uncertain_and_the_same_send_is_held(slow):
    slow.queue = [call("notify", HELLO, cid="first"), call("python_execute", {"code": "print('checking')"}, cid="mid"),
                  call("notify", HELLO, cid="again"),
                  reply("The message may already have gone out; I did not send it again.")]
    task, seen = run_send(slow)
    assert SENT == [("prince", HELLO["text"])]  # once: the repeat was held, not sent
    kinds = kinds_of(task["task_id"])
    assert kinds.count("intent.recorded") == 1 and "intent.done" not in kinds
    assert kinds.index("intent.recorded") < kinds.index("intent.uncertain") < kinds.index("intent.refused")
    (unc,) = payloads(task["task_id"], "intent.uncertain")
    assert unc["tool"] == "notify" and unc["args_hash"] == HASH and unc["summary"] == SUMMARY and unc["why"] == "timed out"
    (held,) = payloads(task["task_id"], "intent.refused")
    assert held["args_hash"] == HASH and held["first_step"] == 1  # (the call between clears the loop guard, as a model's would)
    failed = [p for p in payloads(task["task_id"], "tool.failed") if p["name"] == "notify"]
    assert failed[0]["output"].find("did not answer within") >= 0 and failed[1]["refused"] is True
    # nothing ever said it finished: recovery and a resume see a send that may have gone out
    assert get_journal().open_intents(task["task_id"]) == [{"tool": "notify", "args_hash": HASH, "summary": SUMMARY, "step": 1}]
    wire = [e["event"] for e in seen if e["type"] == "intent"]
    assert wire == ["recorded", "uncertain", "refused"]


def test_a_send_that_was_refused_by_the_server_is_done_and_may_be_retried(refusing):
    refusing.queue = [call("notify", HELLO, cid="first"), call("python_execute", {"code": "print('retry')"}, cid="mid"),
                      call("notify", HELLO, cid="again"), reply("Sent on the second try.")]
    task, _ = run_send(refusing)
    assert SENT == [None, ("prince", HELLO["text"])]
    kinds = kinds_of(task["task_id"])
    assert kinds.count("intent.done") == 2 and "intent.uncertain" not in kinds and "intent.refused" not in kinds
    assert [p["ok"] for p in payloads(task["task_id"], "intent.done")] == [False, True]
    assert get_journal().open_intents(task["task_id"]) == []


def test_an_uncertain_send_is_not_an_outcome_the_answer_may_claim(slow):
    slow.queue = [call("notify", HELLO, cid="first"), reply("Sent: the build is green."),
                  reply("I could not confirm it went out: the call timed out.")]
    task, _ = run_send(slow)
    assert "could not confirm" in task["result"]  # agent.py OUTCOME_CLAIMS: no send succeeded, so "sent" is asked about


@pytest.mark.parametrize("output, why", [
    (TOOL_TIMED_OUT.format(name="notify", limit=180), "timed out"),
    ("Observed output of cmd `python_execute` executed:\n{'observation': 'Execution timeout after 60 seconds', 'success': False}", "timed out"),
    ("Error: TimeoutError: timed out", "timed out"),
    ("Error: requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='api.telegram.org'): Read timed out.", "timed out"),
    ("Error: ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the remote host", "connection lost"),
    ("Error: http.client.RemoteDisconnected: Remote end closed connection without response", "connection lost"),
    ("Error: ConnectionAbortedError: [WinError 10053]", "connection lost"),
])
def test_what_says_a_send_may_have_gone_out(output, why):
    assert uncertain(output) == why


@pytest.mark.parametrize("output", [
    "Error: ConnectionRefusedError: [WinError 10061] No connection could be made",
    "Error: 400 Bad Request: chat not found",
    "Error: unknown argument(s) ['sheet_name']",
    "",
    None,
])
def test_what_says_it_did_not(output):
    assert uncertain(output) is None


def test_the_journal_type():
    assert _journal_type({"type": "intent", "event": "uncertain"}) == "intent.uncertain"
