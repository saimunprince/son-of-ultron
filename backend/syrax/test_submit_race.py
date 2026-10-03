"""Live 2026-10-03: the boot cycle and a human "hi" submitted while the agent
was still being built; the cycle never got its task and hung with its
objective ACTIVE. One submit at a time, one agent build, and a hung build
fails instead of freezing SYRAX."""

import asyncio
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax import core as core_mod  # noqa: E402
from syrax.agent import SyraxAgent  # noqa: E402
from syrax.core import Core  # noqa: E402
from syrax.journal import Journal  # noqa: E402
from syrax.test_autonomy import make  # noqa: E402


class FakeAgent:
    step_limit_hit = False

    def reset_conversation(self):
        pass

    def repair_memory(self, aborted=False):
        pass

    def export_context(self):
        return {}

    async def run(self, request):
        await asyncio.sleep(0.2)
        return f"done: {request}"


def test_two_submits_during_the_agent_build_start_one_task(tmp_path):
    c = Core(Journal(tmp_path / "j.db"))
    c.devloop.begin_task = lambda: None
    builds = []

    async def build():
        builds.append(1)
        await asyncio.sleep(0.3)  # the MCP connect at boot
        return FakeAgent()

    c._build_agent = build

    async def both():
        a, b = await asyncio.gather(c.submit("objective work", None, None, kind="autonomous"), c.submit("hi", "hi", "s1"))
        await c.wait()
        return a, b

    a, b = asyncio.run(both())
    assert len(builds) == 1
    assert (a is None) != (b is None)  # exactly one started; the other was told SYRAX is busy
    started = [t for t in c.journal.tasks(limit=10)]
    assert len(started) == 1 and started[0]["status"] == "SUCCESS"


def test_a_hung_agent_build_fails_instead_of_hanging(tmp_path, monkeypatch):
    c = Core(Journal(tmp_path / "j.db"))
    monkeypatch.setattr(core_mod, "AGENT_CREATE_TIMEOUT_S", 0.2)

    async def never(cls, **kw):
        await asyncio.sleep(60)

    monkeypatch.setattr(SyraxAgent, "create", classmethod(never))

    async def go():
        try:
            await c.ensure_agent()
        except RuntimeError as e:
            return str(e)

    assert "MCP servers not answering" in asyncio.run(asyncio.wait_for(go(), 5))
    assert c.agent is None


def test_a_cycle_whose_task_cannot_start_reopens_its_objective(tmp_path, monkeypatch):
    j, core, a = make(tmp_path)
    monkeypatch.setattr("syrax.autonomy.resource_pressure", lambda: None)

    async def broken(*args, **kw):
        raise RuntimeError("building the agent took over 240s")

    core.submit = broken
    o = j.add_objective_sync("verify desktop", source="selfmodel", check={"kind": "tool_verified", "tool": "desktop"}, key="d")
    rep = asyncio.run(a.run_once(force=True))
    assert rep.outcome == "SKIPPED" and "could not start" in rep.reason
    assert j.objective(o["id"])["status"] == "OPEN"
