"""A benchmark case that runs out of time is journaled as a timeout, not as a human's stop.
run_case awaited core.wait() under wait_for without a shield: on timeout wait_for cancelled Core.wait, whose
gather cancelled the task itself with the default reason before core.cancel(reason) ran, so the case read
"aborted by human" (quality.py run_case had the same bug, run #39, and shields it)."""

import asyncio

from syrax import codebench
from syrax import core as core_mod
from syrax.journal import Journal


class SlowCore:
    """The real Core.wait / cancel / busy over a task that never finishes on its own; the cancelled task
    journals its cancel_reason the way Core._run does."""

    wait = core_mod.Core.wait
    cancel = core_mod.Core.cancel
    _cancel_now = core_mod.Core._cancel_now
    busy = core_mod.Core.busy

    def __init__(self, j):
        self.journal, self.current, self.agent = j, None, None

    async def submit(self, goal, said, session_id, kind="conversation", max_steps=None):
        t = self.journal.start_task_sync(said, kind=kind)
        self.current = core_mod.Running(task_id=t, goal=goal, session_id=session_id, kind=kind)
        self.current.task = asyncio.ensure_future(self._run(t))
        return t

    async def _run(self, t):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            reason = self.current.cancel_reason
            await self.journal.record("task.cancelled", {"error": reason, "error_class": core_mod.cancel_class(reason)}, task_id=t)
            raise


def test_a_case_that_runs_out_of_time_is_journaled_as_a_timeout(tmp_path):
    j = Journal(tmp_path / "j.db")
    core = SlowCore(j)
    case = codebench.CASES[0]
    res = asyncio.run(codebench.run_case(core, case, ws=tmp_path / "ws", timeout=0.3))
    cancelled = [e for e in j.events(res["task_id"]) if e["type"] == "task.cancelled"]
    assert len(cancelled) == 1
    assert "ran out of time" in cancelled[0]["payload"]["error"]
    assert cancelled[0]["payload"]["error_class"] != "human"
    assert not res["ok"] and not res["stopped"]
