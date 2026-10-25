"""Audit 2026-10-25 ("Task runtime"): task.failed carried only free text. It now also carries an error_class
(journal | brain | timeout | tool | other), and task.cancelled says who stopped the task (deadline | human |
quality_timeout | other). Pure additive payload fields: the event sequences test_bridge pins are unchanged."""

import asyncio
import sqlite3

import pytest

from app.agent.toolcall import ToolCallAgent
from app.tool.base import BaseTool
from syrax import core as core_mod
from syrax.agent import SyraxAgent, ToolCrash
from syrax.brains import BrainError
from syrax.journal import Journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, get_journal, recv_until, reply, script, server  # noqa: F401


def terminal(j, task_id):
    ev = [e for e in j.events(task_id) if e["type"] in ("task.failed", "task.cancelled")]
    assert len(ev) == 1, ev
    return ev[0]


def run_task(text="go"):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": text})
        seen = drain_until_idle(ws)
    j = get_journal()
    task = j.tasks()[0]
    return task, terminal(j, task["task_id"]), seen


def test_a_journal_failure_is_classed_journal(script, monkeypatch):
    script.queue = [reply("I did answer.")]
    orig = Journal.record_sync

    def flaky(self, type_, payload=None, task_id=None, volatile=None, dedupe_key=None):
        if type_ == "final":  # the certifying write fails; the terminal mark itself can still be written
            raise sqlite3.OperationalError("disk I/O error")
        return orig(self, type_, payload, task_id, volatile, dedupe_key)

    monkeypatch.setattr(Journal, "record_sync", flaky)
    task, ev, seen = run_task("hi")
    assert any(e["type"] == "error" and "Journal unavailable" in e["message"] for e in seen)
    assert task["status"] == "FAILED" and task["error"].startswith("journal unavailable: disk I/O error")
    assert ev["type"] == "task.failed" and ev["payload"]["error_class"] == "journal"
    assert any(e["type"] == "task" and e["event"] == "failed" and e.get("error_class") == "journal" for e in seen)


class Boomer(BaseTool):
    name: str = "boomer"
    description: str = "a tool whose call path crashes"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self):
        return "fine"


def test_an_exception_escaping_a_tool_call_is_classed_tool(script, monkeypatch):
    """Upstream turns a tool's own exceptions into a failed result (test_bridge: the task continues). What escapes
    the call path anyway fails the task as "tool", and the error names the tool."""
    patched = SyraxAgent.create.__func__

    async def create(cls, **kw):
        agent = await patched(cls, **kw)
        agent.available_tools.add_tool(Boomer())
        return agent

    monkeypatch.setattr(SyraxAgent, "create", classmethod(create))
    orig = ToolCallAgent.execute_tool

    async def crash(self, command):
        if command.function.name == "boomer":
            raise RuntimeError("the call exploded")
        return await orig(self, command)

    monkeypatch.setattr(ToolCallAgent, "execute_tool", crash)
    script.queue = [call("boomer", {}, cid="boom1"), reply("never reached")]
    task, ev, seen = run_task("boom")
    assert task["status"] == "FAILED" and task["error"] == "boomer crashed: the call exploded"
    assert ev["type"] == "task.failed" and ev["payload"] == {"error": "boomer crashed: the call exploded", "error_class": "tool"}
    assert any(e["type"] == "error" and e["message"] == "boomer crashed: the call exploded" for e in seen)
    assert not any(e["type"] == "final" for e in seen)


@pytest.mark.parametrize("exc, expected, text", [
    (BrainError("All brains failed. Gemini: 429 | Groq: 413"), "brain", "All brains failed"),
    (asyncio.TimeoutError(), "timeout", "TimeoutError"),
    (RuntimeError("brain melted"), "other", "brain melted"),  # test_bridge's LLM error, classed honestly as unknown
])
def test_a_brain_failure_a_timeout_and_anything_else(script, exc, expected, text):
    async def boom():
        raise exc

    script.queue = [boom]
    task, ev, seen = run_task("x")
    assert task["status"] == "FAILED" and text in task["error"]
    assert ev["type"] == "task.failed" and ev["payload"]["error_class"] == expected


def test_a_human_stop_is_classed_human(script):
    script.queue = [call("slow", {}, cid="call_slow")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "wait"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "stop"})
        seen = drain_until_idle(ws)
    j = get_journal()
    task = j.tasks()[0]
    ev = terminal(j, task["task_id"])
    assert task["status"] == "CANCELLED" and ev["payload"] == {"error": "aborted by human", "error_class": "human"}
    assert [e["text"] for e in seen if e["type"] == "notice"] == ["Task aborted."]  # a human's stop reads as before


def test_the_classifiers():
    assert core_mod.cancel_class("aborted by human") == "human"
    assert core_mod.cancel_class("dismissed by human: too late") == "human"
    assert core_mod.cancel_class("the quality case ran out of time (240 s)") == "quality_timeout"
    assert core_mod.cancel_class("ran out of time: the task's deadline (30 min) passed") == "deadline"
    assert core_mod.cancel_class("the benchmark case ran out of time (9 s)") == "other"
    assert core_mod.cancel_class("") == "other"
    assert core_mod.error_class(sqlite3.OperationalError("disk I/O error")) == "journal"
    assert core_mod.error_class(BrainError("All brains failed.")) == "brain"
    assert core_mod.error_class(RuntimeError("All brains failed. x")) == "brain"
    assert core_mod.error_class(asyncio.TimeoutError()) == "timeout"
    crash = ToolCrash("browser_exec", RuntimeError("page gone"))
    assert core_mod.error_class(crash) == "tool" and str(crash) == "browser_exec crashed: page gone"
    timed = ToolCrash("x", TimeoutError())
    timed.__cause__ = TimeoutError()
    assert core_mod.error_class(timed) == "timeout"  # a crash whose cause is a timeout is a timeout
    assert core_mod.error_class(ValueError("x")) == "other"
