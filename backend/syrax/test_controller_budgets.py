"""Mission 2026-10-28: the autonomy controller has explicit, persisted states and records why it chose an objective
over the others; SYRAX's own work has a daily budget; every task has a tool-call budget (steps bounded the model's
turns, but one turn may call many tools)."""

import asyncio
import json

from syrax import agent as agent_mod
from syrax import autonomy as auto
from syrax.journal import get_journal
from syrax.test_agent_loops import run_task, tool_texts  # noqa: F401
from syrax.test_autonomy import make, use_tool
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401


def test_a_task_ends_when_its_tool_call_budget_is_spent(script, monkeypatch):
    monkeypatch.setattr(agent_mod, "TOOL_BUDGET_HUMAN", 3)
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    actions = ["summary", "identity", "capabilities", "weaknesses", "performance"]  # all different: no loop guard
    script.queue = [call("self_inspect", {"action": a}, cid=f"c{i}") for i, a in enumerate(actions)] + [reply("never")]
    task = run_task(core, "Inspect everything")
    assert task["status"] == "PARTIAL"  # ended by a bound: never reported as done
    events = get_journal().events(task["task_id"])
    final = [e for e in events if e["type"] == "final"][-1]["payload"]["text"]
    assert final.startswith("Stopped: this task used its budget of 3 tool calls")
    spent = [e for e in events if e["type"] == "budget.exhausted"]
    assert spent and spent[0]["payload"]["budget"] == 3
    ran = [e for e in events if e["type"] in ("tool.completed", "tool.failed")]
    assert ran[-1]["payload"]["output"].startswith("Stopped: this task used its budget")  # the 4th call did not run
    assert len(script.queue) == 2  # one call per model turn: the 5th call and the reply were never asked for


def test_own_work_has_a_daily_budget_the_operator_s_cycle_does_not_spend(tmp_path, monkeypatch):
    j, core, a = make(tmp_path)
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    monkeypatch.setattr(auto, "DAILY_TASKS", 2)
    a.set_enabled(True)
    for _ in range(2):
        j.start_task_sync("earlier own work", kind="autonomous")
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "SKIPPED" and "daily budget spent: 2 of 2" in rep.reason and core.submitted == []
    assert asyncio.run(a.run_once(force=True)).outcome != "SKIPPED"  # cycle_now is the operator's own choice


def test_the_controller_records_its_states_and_why_it_chose(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["desktop", "terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    a.set_enabled(True)
    first = j.add_objective_sync("read the system info", reason="the owner asked", priority=1,
                                 check={"kind": "tool_verified", "tool": "desktop"})
    other = j.add_objective_sync("a later one", reason="less urgent", priority=4, check={"kind": "tool_verified", "tool": "desktop"})
    core.script = [lambda tid: (use_tool("desktop")(tid, j), "desktop returned system info")[1]]
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "RAN" and rep.objective_id == first["id"]
    events = j.recent_events()
    chosen = [e["payload"] for e in events if e["type"] == "goal.selected"]
    assert chosen and chosen[0]["objective_id"] == first["id"] and chosen[0]["reason"] == "the owner asked"
    assert other["id"] in [x["id"] for x in chosen[0]["alternatives"]] and "highest priority" in chosen[0]["rule"]
    states = [e["payload"]["state"] for e in sorted(events, key=lambda e: e["id"]) if e["type"] == "autonomy.state"]
    assert states == ["OBSERVING", "SELECTING", "WORKING", "VERIFYING", "WAITING"]
    saved = json.loads(j.get_meta("autonomy_state"))
    assert saved["state"] == "WAITING" and saved["last_outcome"] == "RAN"
    fresh = auto.Autonomy(core, j)  # a restart reads where the controller stood
    assert fresh.status()["state"]["state"] == "WAITING"
