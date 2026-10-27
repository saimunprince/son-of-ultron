"""Review 2026-10-27: the queue stalled for good when a queued request failed to start. _start_next's error was only
logged and nothing restarted the queue: after a restart whose agent build failed, every queued request stayed
PENDING; a request removed while _start_next was starting it ("task is CANCELLED; refusing task.started") left the
requests behind it waiting; and the autonomy cycle answered BUSY "a human request is waiting" for ever. Now a request
that cannot start is settled with its reason and the next one is tried, a removal waits for a start under way, and an
idle core with waiting requests restarts its queue when it is asked for it."""

import asyncio
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax.core import Core  # noqa: E402
from syrax.journal import Journal  # noqa: E402


class QuickAgent:
    step_limit_hit = False

    def __init__(self):
        self.runs = []

    def reset_conversation(self):
        pass

    def repair_memory(self, aborted=False):
        pass

    def export_context(self):
        return []

    async def run(self, request):
        self.runs.append(request)
        await asyncio.sleep(0)
        return f"done: {request}"


def make(tmp_path, builds=None):
    """A core whose agent build fails once per entry of ``builds`` that is an exception."""
    c = Core(Journal(tmp_path / "j.db"))
    c.devloop.begin_task = lambda: None
    agent = QuickAgent()
    plan = list(builds or [])

    async def build():
        if plan:
            e = plan.pop(0)
            if isinstance(e, BaseException):
                raise e
        return agent

    c._build_agent = build
    return c, agent


def pending(c, *goals):
    return [c.journal.start_task_sync(g, kind="conversation", pending=True) for g in goals]


def test_after_a_restart_whose_agent_build_fails_the_next_request_still_starts(tmp_path):
    c, agent = make(tmp_path, builds=[RuntimeError("building the agent took over 240s (MCP servers not answering)")])
    a, b = pending(c, "first wish", "second wish")

    async def go():
        try:
            out = await c.requeue_after_boot()
        except Exception as e:  # the old core let the failure out and left both waiting
            out = {"error": str(e)}
        await c.wait()
        return out

    out = asyncio.run(asyncio.wait_for(go(), 20))
    ra, rb = c.journal.task(a), c.journal.task(b)
    assert ra["status"] == "CANCELLED" and "could not start" in ra["error"] and "MCP servers" in ra["error"]
    assert rb["status"] == "SUCCESS" and agent.runs == ["second wish"]
    assert out.get("started") == b and c._pending() == []


def test_a_request_removed_while_it_is_being_started_never_stalls_the_one_behind_it(tmp_path):
    c, agent = make(tmp_path)
    a, b = pending(c, "first wish", "second wish")
    removal = {}

    async def go():
        async def observe(ev):  # the human removes the first request just as the queue starts it
            if ev.get("type") == "notice" and "Queued request starting" in ev.get("text", "") and "task" not in removal:
                removal["task"] = asyncio.ensure_future(c.cancel_queued(a, note="changed my mind"))
                await asyncio.wait([removal["task"]], timeout=0.5)

        c.subscribe(observe)
        try:
            await c._start_next()
        except Exception:
            pass  # the old core: "task ... is CANCELLED; refusing task.started"
        await c.wait()
        await c.wait()  # the first one's end starts the next
        removed = await removal["task"]
        await c.wait()
        return removed

    removed = asyncio.run(asyncio.wait_for(go(), 20))
    ra, rb = c.journal.task(a), c.journal.task(b)
    if removed:
        assert ra["status"] == "CANCELLED" and "first wish" not in agent.runs
    else:  # the removal came too late: the request had started, and ran
        assert ra["status"] == "SUCCESS"
    assert rb["status"] == "SUCCESS" and "second wish" in agent.runs
    assert c._pending() == []


def test_an_idle_core_with_a_waiting_request_restarts_its_queue_when_the_cycle_asks(tmp_path, monkeypatch):
    c, agent = make(tmp_path)
    monkeypatch.setattr("syrax.autonomy.resource_pressure", lambda: None)

    async def go():
        await c.requeue_after_boot()  # booted with nothing waiting
        (a,) = pending(c, "a wish nobody started")  # e.g. left behind by a start that failed
        rep = await c.autonomy.run_once(force=True)
        kick = getattr(c, "_queue_kick", None)
        if kick is not None:
            await kick
        await c.wait()
        return a, rep

    a, rep = asyncio.run(asyncio.wait_for(go(), 20))
    assert rep.outcome == "BUSY" and "human request" in rep.reason  # the human goes first, as before
    assert c.journal.task(a)["status"] == "SUCCESS" and agent.runs == ["a wish nobody started"]
