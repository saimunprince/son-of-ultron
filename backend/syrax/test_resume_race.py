"""Review 2026-10-27: Core.resume checked ``busy`` without the submit lock, and ``busy`` was False while ``_begin``
still awaited the agent build (and the worktree, the routing). A RESUME made in that window passed, both paths
launched, and two coroutines drove one agent; _begin's reset_conversation wiped the resumed context. Now SYRAX is
busy while a task starts and a resume holds the submit lock from its busy check to its launch."""

import asyncio
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax.core import Core  # noqa: E402
from syrax.journal import Journal  # noqa: E402


class Memory:
    def __init__(self):
        self.messages = []

    def add_message(self, m):
        self.messages.append(m)


class FakeAgent:
    step_limit_hit = False

    def __init__(self):
        self.runs = []
        self.memory = Memory()
        self.imported = []

    def reset_conversation(self):
        pass

    def repair_memory(self, aborted=False):
        pass

    def export_context(self):
        return []

    def import_context(self, ctx):
        self.imported.append(ctx)

    async def run(self, request):
        self.runs.append(request)
        await asyncio.sleep(0.05)
        return f"done: {request}"


def interrupted(j: Journal, goal: str) -> str:
    t = j.start_task_sync(goal, kind="conversation")
    j.record_sync("think", {"step": 1, "content": "working"}, task_id=t)
    j.record_sync("task.interrupted", {"error": "restart", "recovery": {"state": "RESUMABLE", "operation_state": "NOT_STARTED"}},
                  task_id=t)
    return t


def test_a_resume_while_a_submit_is_still_starting_does_not_launch_a_second_task(tmp_path):
    c = Core(Journal(tmp_path / "j.db"))
    c.devloop.begin_task = lambda: None
    t = interrupted(c.journal, "the old conversation")
    agent = FakeAgent()

    async def go():
        building, release = asyncio.Event(), asyncio.Event()

        async def build():  # the MCP connect at boot: the submit sits here, its task not launched yet
            building.set()
            await release.wait()
            return agent

        c._build_agent = build
        sub = asyncio.create_task(c.submit("hi", "hi", "s1"))
        await building.wait()
        busy_while_starting = c.busy
        res = asyncio.create_task(c.resume(t, "s2"))
        for _ in range(20):  # let the resume reach whatever it waits on
            await asyncio.sleep(0)
        release.set()
        started, problem = await sub, await res
        await c.wait()
        return busy_while_starting, started, problem

    busy_while_starting, started, problem = asyncio.run(go())
    assert busy_while_starting is True
    assert started is not None and problem == "Already executing. Stop it first."
    assert agent.runs == ["hi"]  # one coroutine drove the agent
    assert c.journal.task(t)["status"] == "INTERRUPTED"  # the old conversation is still there to resume
    assert c.journal.task(started)["status"] == "SUCCESS"


def test_two_resumes_of_the_same_task_start_it_once(tmp_path):
    c = Core(Journal(tmp_path / "j.db"))
    c.devloop.begin_task = lambda: None
    t = interrupted(c.journal, "the old conversation")
    agent = FakeAgent()

    async def go():
        building, release = asyncio.Event(), asyncio.Event()

        async def build():
            building.set()
            await release.wait()
            return agent

        c._build_agent = build
        first = asyncio.create_task(c.resume(t, "s1"))
        await building.wait()
        second = asyncio.create_task(c.resume(t, "s2"))
        for _ in range(20):
            await asyncio.sleep(0)
        release.set()
        out = await first, await second
        await c.wait()
        return out

    a, b = asyncio.run(go())
    assert a is None and b == "Already executing. Stop it first."
    assert len(agent.runs) == 1
    assert c.journal.task(t)["status"] == "SUCCESS"
