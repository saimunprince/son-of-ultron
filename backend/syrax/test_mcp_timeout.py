"""Audit 2026-10-25 ("Task runtime"): an MCP tool (browser_exec, browser_screenshot, any tool an MCP server
provides) had no timeout, so one hung call held the single task slot until a human stopped it. Such a call is
abandoned after agent.MCP_TOOL_TIMEOUT_S with a failed result, journaled tool.failed, and the task goes on.
Tools with a cap of their own (python_execute, release, ...) are never wrapped."""

import asyncio
import time

import pytest

from app.tool.base import BaseTool
from app.tool.mcp import MCPClientTool
from syrax import agent as agent_mod
from syrax import browser
from syrax import core as core_mod
from syrax.agent import SyraxAgent
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, get_journal, recv_until, reply, script, server  # noqa: F401


class HangingBrowser(BaseTool):  # a browser_* tool, as Browser Use's MCP server names them
    name: str = "browser_hang"
    description: str = "a page that never answers"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self):
        await asyncio.sleep(30)
        return "never"


class HangingMCP(MCPClientTool):  # any other MCP server's tool: known by its class, not its name
    name: str = "mcp_hang"
    description: str = "a server that never answers"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self, **kwargs):
        await asyncio.sleep(30)
        return "never"


def with_hanging_tools(monkeypatch):
    async def ensure():
        return None

    monkeypatch.setattr(browser, "ensure_browser", ensure)
    monkeypatch.setattr(agent_mod, "MCP_TOOL_TIMEOUT_S", 1.0)
    patched = SyraxAgent.create.__func__

    async def create(cls, **kw):
        agent = await patched(cls, **kw)
        agent.available_tools.add_tool(HangingBrowser())
        agent.available_tools.add_tool(HangingMCP())
        return agent

    monkeypatch.setattr(SyraxAgent, "create", classmethod(create))


def run(script, tool_call):
    script.queue = [tool_call, reply("done")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "look at the page"})
        started = time.monotonic()
        res, _ = recv_until(ws, "tool_result")
        elapsed = time.monotonic() - started
        final, _ = recv_until(ws, "final")
        drain_until_idle(ws)
    j = get_journal()
    task = j.tasks()[0]
    steps = [e for e in j.events(task["task_id"]) if e["type"] in ("tool.completed", "tool.failed")]
    return res, elapsed, task, steps


@pytest.mark.parametrize("name", ["browser_hang", "mcp_hang"])
def test_an_mcp_tool_that_never_answers_is_abandoned_and_the_task_goes_on(script, monkeypatch, name):
    with_hanging_tools(monkeypatch)
    res, elapsed, task, steps = run(script, call(name, {}, cid="hang1"))
    assert res["name"] == name and res["ok"] is False
    assert res["output"] == (f"Error: {name} did not answer within 1 s; the call was abandoned (the page or server may "
                             "still be busy): try once more with a simpler step, or report it")
    assert elapsed < 10  # the 1 s cap ended the call, not the 30 s sleep
    assert [e["type"] for e in steps] == ["tool.failed"] and steps[0]["payload"]["ok"] is False
    assert task["status"] == "SUCCESS" and task["result"] == "done"  # the task reached its final


def test_python_execute_keeps_its_own_cap(script, monkeypatch):
    with_hanging_tools(monkeypatch)  # MCP cap 1 s; python_execute's own 600 s cap stands
    res, elapsed, task, steps = run(script, call("python_execute", {"code": "import time; time.sleep(3); print('slow ok')"}, cid="py1"))
    assert res["ok"] is True and "slow ok" in res["output"] and elapsed >= 3
    assert [e["type"] for e in steps] == ["tool.completed"] and task["status"] == "SUCCESS"


def test_only_mcp_tools_without_a_cap_of_their_own_are_wrapped(script, monkeypatch):
    with_hanging_tools(monkeypatch)
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        agent = core_mod.get_core().agent
        assert agent.is_mcp_tool("browser_hang") and agent.is_mcp_tool("mcp_hang") and agent.is_mcp_tool("browser_exec")
        for name in ("python_execute", "release", "skill_create", "skill_test", "experiment", "quality", "desktop",
                     "str_replace_editor", "ask_human", "slow", "self_inspect", "terminate"):
            assert not agent.is_mcp_tool(name), name
    assert agent_mod.OWN_TIMEOUT_TOOLS >= {"python_execute", "release", "skill_create", "skill_test", "experiment",
                                           "quality", "desktop", "str_replace_editor", "ask_human"}
