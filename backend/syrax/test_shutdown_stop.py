"""Review 2026-10-27: a restart (`syrax.py --restart`, SYRAX restarting itself into new code) sent {"type": "stop"}
and waited for idle; the task's cleanup broadcast idle and then started the next queued request (task.started on its
PENDING row) just before taskkill. At the next boot that request was INTERRUPTED, not PENDING, so
requeue_after_boot never saw it. And since phase 7 (auth.py) the launcher's stop, sent without an Origin and
without the token, was refused before it arrived. Now the launcher presents the token and says "shutdown"; the core
holds its queue, answers `stopped` once the task ended, and the queued request is still PENDING for the next boot."""

import asyncio
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax import server  # noqa: E402
from syrax.core import Core  # noqa: E402
from syrax.journal import Journal  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class BlockingAgent:
    """"first" runs until it is cancelled; anything else answers at once."""

    step_limit_hit = False

    def __init__(self):
        self.runs = []
        self.running = asyncio.Event()

    def reset_conversation(self):
        pass

    def repair_memory(self, aborted=False):
        pass

    def export_context(self):
        return []

    async def run(self, request):
        self.runs.append(request)
        if request == "first":
            self.running.set()
            await asyncio.Event().wait()
        return f"done: {request}"

    async def shutdown(self):
        pass


class FakeWS:
    headers = {"origin": None, "user-agent": "launcher"}

    def __init__(self):
        self.sent = []

    async def send_json(self, event):
        self.sent.append(event)


def session_for(core):
    s = object.__new__(server.Session)  # a session on this core, without the process-wide one
    s.ws, s.probe, s.id, s.core, s.closed, s._lock, s.aux = FakeWS(), True, "launcher", core, False, asyncio.Lock(), set()
    return s


def core_with(tmp_path):
    c = Core(Journal(tmp_path / "j.db"))
    c.devloop.begin_task = lambda: None
    agent = BlockingAgent()

    async def build():
        return agent

    c._build_agent = build
    return c, agent


def test_a_shutdown_stop_leaves_the_queued_request_pending(tmp_path):
    c, agent = core_with(tmp_path)
    s = session_for(c)

    async def go():
        a = await c.submit("first", "first", "s1")
        await agent.running.wait()
        b = await c.submit("second", "second", "s1", queue=True)
        await s.handle({"type": "stop", "reason": "shutdown"})
        await c.wait()
        held = (c.journal.task(a)["status"], c.journal.task(b)["status"], list(agent.runs))
        c._queue_hold_until = 0.0  # the process was not killed after all: the queue moves on
        started = await c._start_next()
        await c.wait()
        return b, held, started

    b, held, started = asyncio.run(go())
    assert held == ("CANCELLED", "PENDING", ["first"])
    assert {"type": "stopped", "queue_held": True} in s.ws.sent
    assert started == b and c.journal.task(b)["status"] == "SUCCESS"


def test_core_shutdown_does_not_start_a_queued_request(tmp_path):
    c, agent = core_with(tmp_path)

    async def go():
        await c.submit("first", "first", "s1")
        await agent.running.wait()
        b = await c.submit("second", "second", "s1", queue=True)
        await c.shutdown()
        return b

    b = asyncio.run(go())
    assert c.journal.task(b)["status"] == "PENDING" and agent.runs == ["first"]


def test_the_launcher_stop_presents_the_token_says_shutdown_and_waits_for_stopped(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("syrax_launcher_stop", ROOT / "syrax.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    tok = tmp_path / "ws.token"
    tok.write_text("tok-123\n", encoding="utf-8")
    monkeypatch.setenv("SYRAX_TOKEN_FILE", str(tok))
    seen = {"urls": [], "sent": []}
    replies = [{"type": "state", "state": "booting"}, {"type": "state", "state": "idle"}, {"type": "stopped", "queue_held": True}]

    class Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def send(self, text):
            seen["sent"].append(json.loads(text))

        async def recv(self):
            if replies:
                return json.dumps(replies.pop(0))
            await asyncio.sleep(60)

    def connect(url, **kw):
        seen["urls"].append(url)
        return Conn()

    monkeypatch.setitem(sys.modules, "websockets", types.SimpleNamespace(connect=connect))
    launcher._cancel_running_task()
    assert seen["sent"] == [{"type": "stop", "reason": "shutdown"}]
    assert len(seen["urls"]) == 1 and "token=tok-123" in seen["urls"][0] and "probe=1" in seen["urls"][0]
    assert replies == []  # the boot's own "idle" did not end the wait; `stopped` did
