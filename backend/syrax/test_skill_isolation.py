"""A registered skill runs off the server's event loop: a skill that blocks
(live 2026-10-12: disk_usage walked C:\\ with os.walk inside async execute and
froze WebSocket, voice and /health) blocks only its own thread, and a call
that runs too long comes back as an error while the server keeps going."""

import asyncio
import time
from typing import ClassVar

from app.tool.base import BaseTool, ToolResult
from app.tool.tool_collection import ToolCollection
from syrax import skills
from syrax.test_skills import GOOD, GOOD_TEST, factory


class Blocking(BaseTool):
    name: ClassVar[str] = "blocking"
    description: ClassVar[str] = "sleeps without awaiting"
    parameters: ClassVar[dict] = {"type": "object", "properties": {"s": {"type": "number"}}, "required": ["s"]}
    risk: ClassVar[str] = "READ_ONLY"

    async def execute(self, s: float) -> ToolResult:
        time.sleep(s)  # the mistake a skill can make: blocking inside async code
        return ToolResult(output=f"slept {s}")


class Broken(Blocking):
    async def execute(self, s: float) -> ToolResult:
        raise RuntimeError("boom")


async def ticks_while(coro, every=0.05):
    n, done = 0, asyncio.ensure_future(coro)
    while not done.done():
        await asyncio.sleep(every)
        n += 1
    return n, done.result()


def test_a_blocking_skill_does_not_stop_the_server_loop():
    live = skills.IsolatedSkill.wrap(Blocking())
    n, out = asyncio.run(ticks_while(live.execute(s=1.0)))
    assert out.output == "slept 1.0" and n >= 10  # the loop kept ticking while the skill slept
    assert (live.name, live.description, live.parameters, live.risk) == ("blocking", "sleeps without awaiting", Blocking.parameters, "READ_ONLY")


def test_a_call_that_runs_too_long_comes_back_as_an_error(monkeypatch):
    monkeypatch.setattr(skills, "SKILL_CALL_TIMEOUT_S", 0.3)
    started = time.monotonic()
    out = asyncio.run(skills.IsolatedSkill.wrap(Blocking()).execute(s=2.0))
    assert time.monotonic() - started < 1.5 and out.error.startswith("`blocking` did not finish within 0 s")


def test_a_skill_error_still_reaches_the_agent():
    try:
        asyncio.run(skills.IsolatedSkill.wrap(Broken()).execute(s=0))
        raise AssertionError("the error was swallowed")
    except RuntimeError as e:
        assert str(e) == "boom"


def test_the_factory_registers_skills_isolated(tmp_path):
    j, f, coll = factory(tmp_path)
    asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    live = coll.tool_map["word_count"]
    assert isinstance(live, skills.IsolatedSkill) and f.loaded["word_count"] is live
    assert live.to_param()["function"]["name"] == "word_count" and live.inner.name == "word_count"
    assert asyncio.run(ToolCollection(live).execute(name="word_count", tool_input={"text": "a b c"})).output == "3"
