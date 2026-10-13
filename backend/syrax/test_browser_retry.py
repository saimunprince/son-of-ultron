"""A browser call whose daemon could not reach the browser never ran, so it
is tried once more after the browser is made sure of (live 2026-10-13: the
first call after a reboot failed while Chrome restarted itself). A call that
lost its connection midway may have run, so it is never repeated."""

import pytest

from app.tool.base import BaseTool, ToolResult
from syrax import browser
from syrax.agent import SyraxAgent
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, get_journal, reply, script, server  # noqa: F401

UNREACHABLE = ("RuntimeError: fatal: BU_CDP_URL=http://127.0.0.1:9333 unreachable after 30s: <urlopen error "
               "[WinError 10061] No connection could be made because the target machine actively refused it>")


def with_browser(monkeypatch, outcomes):
    calls, ensured = [], []

    class FakeBrowser(BaseTool):
        name: str = "browser_exec"
        description: str = "runs browser code"
        parameters: dict = {"type": "object", "properties": {"code": {"type": "string"}}}

        async def execute(self, code: str = ""):
            calls.append(code)
            out = outcomes[min(len(calls), len(outcomes)) - 1]
            return ToolResult(error=out) if out.startswith("RuntimeError") else ToolResult(output=out)

    async def ensure():
        ensured.append(1)
        return None

    monkeypatch.setattr(browser, "ensure_browser", ensure)
    patched = SyraxAgent.create.__func__

    async def create(cls, **kw):
        agent = await patched(cls, **kw)
        agent.available_tools.add_tool(FakeBrowser())
        return agent

    monkeypatch.setattr(SyraxAgent, "create", classmethod(create))
    return calls, ensured


def run(script):
    script.queue = [call("browser_exec", {"code": "print(page_info())"}, cid="b1"), reply("done")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "open the page"})
        drain_until_idle(ws)
    return [e for e in get_journal().events(get_journal().tasks()[0]["task_id"]) if e["type"] in ("tool.completed", "tool.failed")]


def test_a_call_that_never_reached_the_browser_is_tried_once_more(script, monkeypatch):
    calls, ensured = with_browser(monkeypatch, [UNREACHABLE, "Example Domain"])
    results = run(script)
    assert len(calls) == 2 and len(ensured) == 2  # before the call, and before the retry
    assert [e["type"] for e in results] == ["tool.completed"] and "Example Domain" in results[0]["payload"]["output"]


@pytest.mark.parametrize("lost", ["RuntimeError: fatal: WebSocket connection closed", "RuntimeError: no close frame received or sent"])
def test_a_connection_lost_midway_is_never_repeated(script, monkeypatch, lost):
    calls, _ = with_browser(monkeypatch, [lost, "Example Domain"])
    results = run(script)
    assert len(calls) == 1 and [e["type"] for e in results] == ["tool.failed"]
    assert browser.never_ran(UNREACHABLE) and not browser.never_ran(lost)
