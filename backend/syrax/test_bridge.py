"""End-to-end test of the SYRAX WebSocket bridge with a scripted fake LLM.

Run: OPENMANUS_DISABLE_BROWSER_USE=1 .venv/bin/python -m pytest syrax/test_bridge.py -q
"""

import asyncio
import json
import os

import tempfile  # noqa: E402

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")
_tmp_mem = __import__("tempfile").mkdtemp()
os.environ.setdefault("SYRAX_MEMORY_FILE", os.path.join(_tmp_mem, "memory.json"))
os.environ.setdefault("SYRAX_HISTORY_FILE", os.path.join(_tmp_mem, "history.jsonl"))
os.environ.setdefault("SYRAX_BROWSER", "0")
os.environ.setdefault("SYRAX_BRAINS_FILE", os.path.join(tempfile.mkdtemp(), "brains.json"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openai.types.chat import ChatCompletionMessage  # noqa: E402
from openai.types.chat.chat_completion_message_tool_call import (  # noqa: E402
    ChatCompletionMessageToolCall,
    Function,
)

from syrax.brains import BrainRouter  # noqa: E402
from app.tool.base import BaseTool  # noqa: E402
from syrax import server  # noqa: E402
from syrax.agent import SyraxAgent  # noqa: E402

ORIGIN = {"origin": "http://localhost:3000"}


def reply(text):
    return ChatCompletionMessage(role="assistant", content=text)


def call(name, args, text="", cid=None):
    cid = cid or f"call_{name}_{abs(hash(json.dumps(args))) % 10000}"
    return ChatCompletionMessage(
        role="assistant",
        content=text,
        tool_calls=[
            ChatCompletionMessageToolCall(
                id=cid, type="function", function=Function(name=name, arguments=json.dumps(args))
            )
        ],
    )


class Script:
    def __init__(self):
        self.queue = []
        self.seen = []

    async def __call__(self, llm, messages, **kwargs):
        self.seen.append(messages)
        item = self.queue.pop(0)
        if callable(item):
            return await item()
        return item


class SlowTool(BaseTool):
    name: str = "slow"
    description: str = "sleeps"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self):
        await asyncio.sleep(30)
        return "never"


@pytest.fixture
def script(monkeypatch):
    s = Script()

    async def fake(self, messages, **kwargs):
        return await s(self, messages, **kwargs)

    monkeypatch.setattr(BrainRouter, "ask_tool", fake)

    orig_create = SyraxAgent.create.__func__

    async def create(cls, **kw):
        agent = await orig_create(cls, **kw)
        agent.available_tools.add_tool(SlowTool())
        return agent

    monkeypatch.setattr(SyraxAgent, "create", classmethod(create))
    return s


def recv_until(ws, kind, limit=50):
    seen = []
    for _ in range(limit):
        e = ws.receive_json()
        seen.append(e)
        if e["type"] == kind:
            return e, seen
    raise AssertionError(f"no {kind} in {seen}")


def boot(ws):
    hello, _ = recv_until(ws, "hello")
    recv_until(ws, "state")
    return hello


def test_rejects_foreign_origin(script):
    client = TestClient(server.app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()


def boot_all(ws):
    hello, _ = recv_until(ws, "hello")
    brains, _ = recv_until(ws, "brains")
    recv_until(ws, "state")
    return hello, brains


def test_hello_and_brain_panel(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello, brains = boot_all(ws)
        ids = [p["id"] for p in brains["providers"]]
        assert "pollinations" in ids and "ollama" in ids and "gemini" in ids
        poll = next(p for p in brains["providers"] if p["id"] == "pollinations")
        assert poll["enabled"] and not poll["key_required"]
        ws.send_json({"type": "brains_save", "providers": {"gemini": {"api_key": "AIzaTESTKEY12345"}}})
        saved, _ = recv_until(ws, "brains")
        gem = next(p for p in saved["providers"] if p["id"] == "gemini")
        assert gem["has_key"] and gem["enabled"] and gem["key_hint"] == "••••2345"
        assert "AIzaTESTKEY12345" not in json.dumps(saved)  # key never echoed
        ws.send_json({"type": "brains_save", "providers": {"gemini": {"api_key": ""}}})
        cleared, _ = recv_until(ws, "brains")
        assert not next(p for p in cleared["providers"] if p["id"] == "gemini")["has_key"]


def test_chat_reply_ends_turn(script):
    script.queue = [reply("Ami SYRAX. Bol.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert {"python_execute", "ask_human", "terminate"} <= set(hello["tools"])
        ws.send_json({"type": "task", "text": "ke tui?"})
        final, _ = recv_until(ws, "final")
        assert final["text"] == "Ami SYRAX. Bol."
        assert script.queue == []  # exactly one LLM call, no runaway loop


def test_tool_flow_streams_and_terminates(script):
    script.queue = [
        call("python_execute", {"code": "print(6*7)"}, "Hisab kortesi."),
        call("terminate", {"status": "success"}, "Uttor 42. Done."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "6*7 koto?"})
        res, seen = recv_until(ws, "tool_result")
        assert res["name"] == "python_execute" and res["ok"] and "42" in res["output"]
        assert any(e["type"] == "state" and e.get("state") == "acting" for e in seen)
        final, _ = recv_until(ws, "final")
        assert final["text"] == "Uttor 42. Done."


def test_ask_human_roundtrip(script):
    script.queue = [
        call("ask_human", {"inquire": "Kon folder?"}),
        call("terminate", {"status": "success"}, "Thik ache."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "file banao"})
        ask, _ = recv_until(ws, "ask")
        assert ask["question"] == "Kon folder?"
        ws.send_json({"type": "answer", "text": "workspace"})
        res, _ = recv_until(ws, "tool_result")
        assert "workspace" in res["output"]
        recv_until(ws, "final")


def test_abort_repairs_memory_and_next_task_works(script):
    script.queue = [call("slow", {}, cid="call_slow"), reply("Abar ready.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "wait"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "stop"})
        notice, _ = recv_until(ws, "notice")
        assert "aborted" in notice["text"].lower()
        recv_until(ws, "state")
        ws.send_json({"type": "task", "text": "abar?"})
        final, _ = recv_until(ws, "final")
        assert final["text"] == "Abar ready."
    # the dangling tool call must not be sent to the LLM again
    last = script.seen[-1]
    assert not any(getattr(m, "tool_calls", None) and m.tool_calls[0].id == "call_slow" for m in last)
    # and the model is told the old task was cancelled
    assert any("aborted the previous task" in (getattr(m, "content", "") or "") for m in last)


def test_python_execute_does_not_block_loop(script):
    script.queue = [
        call("python_execute", {"code": "import time; time.sleep(3); print('x')"}, cid="call_py"),
        reply("never reached"),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "sleep"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "ping"})
        pong, seen = recv_until(ws, "pong", limit=5)  # must arrive while code runs
        assert not any(e["type"] == "tool_result" for e in seen)
        ws.send_json({"type": "stop"})
        recv_until(ws, "notice")


def test_malformed_message_does_not_kill_session(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_text("not json")
        err, _ = recv_until(ws, "error")
        assert "Malformed" in err["message"]
        ws.send_json({"type": "ping"})
        recv_until(ws, "pong")
