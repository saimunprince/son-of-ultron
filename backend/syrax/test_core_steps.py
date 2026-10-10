"""A step budget belongs to one task: core.submit applies it and the next
task without one is back at the agent's default."""

import asyncio

from syrax.test_bridge import ORIGIN, TestClient, boot, core_mod, reply, script, server  # noqa: F401


def test_submit_applies_a_step_budget_for_one_task_only(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    script.queue = [reply("First."), reply("Second.")]

    async def go():
        await core.submit("one", said="one", session_id=None, kind="autonomous", max_steps=30)
        budget = core.agent.max_steps
        await core.wait()
        await core.submit("two", said="two", session_id=None, kind="conversation")
        default = core.agent.max_steps
        await core.wait()
        return budget, default

    budget, default = asyncio.run(go())
    assert budget == 30
    assert default == type(core.agent).model_fields["max_steps"].default == 20
