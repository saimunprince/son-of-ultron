"""Review 2026-10-27: an autonomous task keeps the human's conversation aside (Core._human_context) and the next
conversation task puts it back. A RESUME of an interrupted conversation left that saved context set, so the next
human message imported it over the resumed conversation and what was just resumed was lost. After a resume the
resumed conversation is the human's conversation."""

import asyncio
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax.core import Core  # noqa: E402
from syrax.journal import Journal  # noqa: E402
from syrax.test_resume_race import interrupted  # noqa: E402


class Memory:
    def __init__(self):
        self.messages = []

    def add_message(self, m):
        self.messages.append(m)


def say(text):
    return {"role": "user", "content": text}


class ContextAgent:
    """Its memory is a list of message dicts; export/import copy it, reset clears it, a run appends the request."""

    step_limit_hit = False

    def __init__(self):
        self.memory = Memory()
        self.memory.messages = [say("the human's earlier chat")]

    def export_context(self):
        return list(self.memory.messages)

    def import_context(self, ctx):
        self.memory.messages = list(ctx)

    def reset_conversation(self):
        self.memory.messages = []

    def repair_memory(self, aborted=False):
        pass

    async def run(self, request):
        self.memory.add_message(say(request))
        await asyncio.sleep(0)
        return f"done: {request}"


def test_the_next_message_after_a_resume_continues_the_resumed_conversation(tmp_path):
    c = Core(Journal(tmp_path / "j.db"))
    c.devloop.begin_task = lambda: None
    c._dirty_repo_info = lambda: None  # the autonomous task never looks at this checkout's files
    agent = ContextAgent()

    async def build():
        return agent

    c._build_agent = build
    t = interrupted(c.journal, "the old conversation")
    c.journal.checkpoint_sync(t, "thinking", completed_steps=[], verified={}, context=[say("the resumed chat")], evidence_state="PARTIAL")

    async def go():
        assert await c.submit("own work", None, None, kind="autonomous")  # keeps the human's chat aside
        await c.wait()
        assert await c.resume(t, "s1") is None
        await c.wait()
        assert await c.submit("and then?", "and then?", "s1")
        await c.wait()

    asyncio.run(go())
    seen = [m.get("content") if isinstance(m, dict) else getattr(m, "content", None) for m in agent.memory.messages]
    assert "the resumed chat" in seen and seen[-1] == "and then?"
    assert "the human's earlier chat" not in seen
    assert c.journal.task(t)["status"] == "SUCCESS"
