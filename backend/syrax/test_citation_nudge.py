"""Phase 6 of the self-improvement plan: an answer that rests on `research`
names its source. When the final answer of a task that researched carries no
URL, SYRAX is asked once for it; the journal records claim.uncited either
way. Spoken answers are exempt (a URL read aloud helps nobody), and so is an
answer that never researched."""

import asyncio

from syrax.agent import CITE_NUDGE
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, get_journal, reply, script, server  # noqa: F401


def run(text, kind="conversation"):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind=kind)
        await core.wait()
        return tid

    tid = asyncio.run(go())
    return core.journal.task(tid), [e for e in get_journal().events(tid) if e["type"] == "claim.uncited"]


def nudged(script):
    return any(CITE_NUDGE in str(m.get("content") if isinstance(m, dict) else getattr(m, "content", "")) for msgs in script.seen for m in msgs)


def test_a_researched_answer_without_a_source_is_asked_once_for_it(script, monkeypatch):
    from syrax import research

    async def fake_research(self, question="", max_sources=4, **_):
        from app.tool.base import ToolResult

        return ToolResult(output="Sources:\n1. https://www.sqlite.org/history.html — SQLite 1.0 was released in August 2000.")

    monkeypatch.setattr(research.ResearchTool, "execute", fake_research)
    script.queue = [
        call("research", {"question": "when was SQLite first released"}),
        reply("SQLite was first released in 2000."),
        reply("SQLite was first released in 2000. Source: https://www.sqlite.org/history.html"),
    ]
    task, uncited = run("Research in what year SQLite was first released and give a source.")
    assert task["result"].endswith("https://www.sqlite.org/history.html")
    assert len(uncited) == 1 and uncited[0]["payload"]["text"].startswith("SQLite was first released in 2000.")
    assert nudged(script) and not script.queue


def test_an_answer_that_never_researched_or_already_cites_is_not_nudged(script, monkeypatch):
    script.queue = [reply("Tokyo.")]
    task, uncited = run("What is the capital of Japan?")
    assert task["result"] == "Tokyo." and uncited == [] and not nudged(script)
    from syrax import research

    async def fake_research(self, question="", max_sources=4, **_):
        from app.tool.base import ToolResult

        return ToolResult(output="Sources:\n1. https://example.org/x — x")

    monkeypatch.setattr(research.ResearchTool, "execute", fake_research)
    script.queue = [call("research", {"question": "x"}), reply("X is 1 (https://example.org/x).")]
    task, uncited = run("Research x.")
    assert task["result"] == "X is 1 (https://example.org/x)." and uncited == [] and not nudged(script)


def test_a_spoken_answer_is_exempt(script, monkeypatch):
    from syrax import research

    async def fake_research(self, question="", max_sources=4, **_):
        from app.tool.base import ToolResult

        return ToolResult(output="Sources:\n1. https://example.org/y — y")

    monkeypatch.setattr(research.ResearchTool, "execute", fake_research)
    script.queue = [call("research", {"question": "y"}), reply("Y is two.")]
    task, uncited = run("Research y.\n\n[Spoken aloud by voice. Answer in one or two short spoken English sentences.]")
    assert task["result"] == "Y is two." and uncited == [] and not nudged(script)
