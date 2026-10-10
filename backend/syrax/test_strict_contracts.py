"""Owner's decision 2026-10-10: an objective needs a machine-verifiable
check. A check-less objective is blocked without spending a task, and a human
cannot add one without a check."""

import asyncio

from syrax import autonomy as auto
from syrax.autonomy import Autonomy
from syrax.journal import Journal
from syrax.server import objective_check_problem
from syrax.test_autonomy import make
from syrax.test_bridge import ORIGIN, TestClient, boot, recv_until, script, server  # noqa: F401


def test_a_check_less_objective_is_blocked_without_spending_a_task(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    a.set_enabled(True)
    o = j.add_objective_sync("make things better", priority=1)
    rep = asyncio.run(a.run_once())
    got = j.objective(o["id"])
    assert rep.verdict == "BLOCKED" and rep.task_id is None and core.submitted == []
    assert got["status"] == "BLOCKED" and "attach a machine check" in got["next_action"]


def test_a_human_cannot_add_an_objective_without_a_machine_check(script):
    assert "a check is required" in objective_check_problem(None)
    assert "kind must be one of" in objective_check_problem({"kind": "task_success"})
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "objective_add", "goal": "be better", "priority": 1})
        assert "a check is required" in recv_until(ws, "notice")[0]["text"]
        ws.send_json({"type": "objective_add", "goal": "be better", "priority": 1, "check": {"kind": "task_success"}})
        assert "kind must be one of" in recv_until(ws, "notice")[0]["text"]
        ws.send_json({"type": "objective_add", "goal": "verify desktop", "priority": 1, "check": {"kind": "tool_verified", "tool": "desktop"}})
        created, _ = recv_until(ws, "objective")
        assert created["event"] == "created" and created["source"] == "human"
