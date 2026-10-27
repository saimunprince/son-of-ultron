"""Review 2026-10-27: a cancel that landed while _run's finally was cleaning up (reset(), a cancelled core.wait() such
as the autonomy loop stopping, shutdown) aborted _clean_repo_after_task half-way (a rollback left half-done) and
skipped the rest: `current` stayed set, no idle was broadcast and the queued request behind the task never started.
Now the cleanup and the idle run to their end, `current` is cleared, the queue moves on, and the cancel is honoured
afterwards."""

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


def setup(tmp_path):
    c = Core(Journal(tmp_path / "j.db"))
    c.devloop.begin_task = lambda: None
    agent = QuickAgent()

    async def build():
        return agent

    c._build_agent = build
    states = []

    async def observe(ev):
        if ev.get("type") == "state":
            states.append(ev.get("state"))

    c.subscribe(observe)
    return c, agent, states


def blocking_cleanup(c, log):
    """The first cleanup (the rollback of a task's edits) waits for `release`; it says when it starts and ends."""
    cleaning, release = asyncio.Event(), asyncio.Event()

    async def clean():
        if "cleaned" in log:
            return
        cleaning.set()
        await release.wait()
        log.append("cleaned")

    c._clean_repo_after_task = clean
    return cleaning, release


def test_a_cancelled_wait_during_the_cleanup_lets_the_cleanup_finish_and_the_queue_move_on(tmp_path):
    c, agent, states = setup(tmp_path)
    log = []

    async def go():
        cleaning, release = blocking_cleanup(c, log)
        a = await c.submit("first", "first", "s1")
        first = c.current.task
        await cleaning.wait()
        b = await c.submit("second", "second", "s1", queue=True)
        waiter = asyncio.create_task(c.wait())  # e.g. the autonomy cycle waiting for its task, then stopped
        await asyncio.sleep(0)
        waiter.cancel()  # gather cancels the task it waits for: the cancel lands in the cleanup
        for _ in range(5):
            await asyncio.sleep(0)
        release.set()
        await asyncio.gather(waiter, first, return_exceptions=True)
        await c.wait()
        return a, b, first.cancelled()

    a, b, cancelled = asyncio.run(asyncio.wait_for(go(), 20))
    assert log == ["cleaned"]  # the cleanup was not cut half-way
    assert cancelled  # the cancel was honoured once the cleanup was over
    assert "idle" in states and c.current is None
    assert c.journal.task(a)["status"] == "SUCCESS"
    assert c.journal.task(b)["status"] == "SUCCESS" and agent.runs == ["first", "second"]


def test_a_reset_during_the_cleanup_leaves_the_core_idle(tmp_path):
    c, agent, states = setup(tmp_path)
    log = []

    async def go():
        cleaning, release = blocking_cleanup(c, log)
        await c.submit("first", "first", "s1")
        await cleaning.wait()
        reset = asyncio.create_task(c.reset())
        for _ in range(5):
            await asyncio.sleep(0)
        release.set()
        await reset
        return c.busy

    busy = asyncio.run(asyncio.wait_for(go(), 20))
    assert log == ["cleaned"] and busy is False
    assert c.current is None and states[-1] == "idle"
