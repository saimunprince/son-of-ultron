"""Audit 2026-10-29 (lifecycle): submit checked the emergency stop once, then awaited the agent build (up to 240 s),
devloop.begin_task, isolation and the brain routing before the task's coroutine existed. The operator's E-STOP in that
window cancelled nothing (core.current was not set yet) and the task then started and ran tools. The stop is now
checked again right before launch: a self-started task that meets it there ends CANCELLED and never runs."""

import asyncio

from syrax import estop
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, get_journal, script, server  # noqa: F401


def test_a_stop_set_while_own_work_starts_keeps_it_from_running(script, monkeypatch):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    j = get_journal()
    built = core.ensure_agent

    async def build_then_stop():  # the operator presses E-STOP while the agent is still being built
        await built()
        await asyncio.to_thread(estop.set_stop, j, "pressed during start", "operator")

    monkeypatch.setattr(core, "ensure_agent", build_then_stop)
    script.queue = [call("python_execute", {"code": "print('ran')"}, cid="c1"), call("terminate", {"status": "success"}, "done")]
    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(core.submit("own work", "own work", None, kind="autonomous")) is None
        assert not core.busy and core.current is None
        task = j.tasks()[0]
        assert task["goal"] == "own work" and task["status"] == "CANCELLED"
        kinds = [e["type"] for e in j.events(task["task_id"])]
        assert "tool.started" not in kinds and "think" not in kinds
        refused = [e for e in j.recent_events() if e["type"] == "estop.refused"][-1]["payload"]
        assert refused["stage"] == "start" and refused["task_id"] == task["task_id"]
        assert len(script.queue) == 2  # the brain was never asked
        cancelled = [e for e in j.events(task["task_id"]) if e["type"] == "task.cancelled"][-1]["payload"]
        assert cancelled["error_class"] == "human" and "emergency stop" in cancelled["error"]
    finally:
        estop.clear_stop(j, "test over", "operator")
        loop.close()


def test_a_stop_during_a_forced_cycle_is_not_the_objective_s_failed_attempt(tmp_path, monkeypatch):
    # audit 2026-10-29: cycle_now runs detached, so the stop cancels its task without stopping the cycle; the cycle then
    # judged the CANCELLED task a failed attempt (three BLOCKED the objective and derived follow-ups under the stop)
    from syrax import autonomy as auto
    from syrax.test_autonomy import make

    j, core, a = make(tmp_path)
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    o = j.add_objective_sync("Verify the desktop tool", None, 1, "human", {"kind": "tool_verified", "tool": "desktop"})

    async def stopped_mid_task(goal, said, session_id, kind="conversation", **_):
        t = j.start_task_sync(said or goal, kind=kind)
        estop.set_stop(j, "pressed mid-task", "operator")
        j.record_sync("task.cancelled", {"error": "aborted by human"}, task_id=t)
        return t

    monkeypatch.setattr(core, "submit", stopped_mid_task)
    rep = asyncio.run(a.run_once(force=True))
    assert rep.outcome == "STOPPED" and "emergency stop" in rep.reason
    after = j.objective(o["id"])
    assert after["status"] == "OPEN" and after["attempts"] == 0
    assert not [x for x in j.objectives(limit=100) if x["status"] == "BLOCKED"]  # nothing blocked under the stop
