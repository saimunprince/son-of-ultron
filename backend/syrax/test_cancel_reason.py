"""A cancelled task says who or what stopped it. Live 2026-10-12 a quality
case that ran out of time was journaled "aborted by human" although nobody
pressed stop. A human stop still reads "aborted by human" (test_bridge)."""

import asyncio

from fastapi.testclient import TestClient

from syrax import core as core_mod
from syrax import server
from syrax.journal import Journal
from syrax.quality import QualityRunner
from syrax.test_bridge import ORIGIN, boot, call, drain_until_idle, get_journal, recv_until, script  # noqa: F401


def test_a_quality_case_that_runs_out_of_time_says_so(tmp_path):
    j = Journal(tmp_path / "j.db")
    reasons = []

    class SlowCore:
        journal, busy, agent = j, True, None

        async def submit(self, goal, said, session_id, kind="conversation"):
            return j.start_task_sync(said or goal, kind=kind)

        async def wait(self):
            if not reasons:
                await asyncio.sleep(5)

        async def cancel(self, reason="aborted by human"):
            reasons.append(reason)

    runner = QualityRunner(SlowCore(), j, workspace=tmp_path / "ws", case_timeout=1.0)
    asyncio.run(runner.run_case({"id": "slow", "prompt": "be slow", "checks": []}, {}))
    assert reasons == ["the quality case ran out of time (1 s)"]


def test_the_timeout_reason_reaches_a_real_task_before_it_is_cancelled(tmp_path):
    """Core.wait gathers the task: an unshielded wait_for timeout cancelled the task itself first."""
    j = Journal(tmp_path / "j.db")
    seen = []

    class TaskCore:
        journal, busy, agent = j, True, None
        reason = "aborted by human"

        async def submit(self, goal, said, session_id, kind="conversation"):
            async def work():
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    seen.append(self.reason)
                    raise
            self.task = asyncio.get_running_loop().create_task(work())
            return j.start_task_sync(said or goal, kind=kind)

        async def wait(self):
            await asyncio.gather(self.task, return_exceptions=True)

        async def cancel(self, reason="aborted by human"):
            self.reason = reason
            self.task.cancel()

    runner = QualityRunner(TaskCore(), j, workspace=tmp_path / "ws", case_timeout=0.5)
    asyncio.run(runner.run_case({"id": "slow", "prompt": "be slow", "checks": []}, {}))
    assert seen == ["the quality case ran out of time (0 s)"]


def test_the_core_journals_the_reason_it_was_given(script):
    script.queue = [call("slow", {}, cid="call_slow")]
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws", headers=ORIGIN) as ws:
            boot(ws)
            ws.send_json({"type": "task", "text": "wait"})
            recv_until(ws, "tool_start")
            client.portal.call(core_mod.get_core().cancel, "the benchmark case ran out of time (9 s)")
            drain_until_idle(ws)
    task = get_journal().tasks()[0]
    assert task["status"] == "CANCELLED" and task["error"] == "the benchmark case ran out of time (9 s)"
