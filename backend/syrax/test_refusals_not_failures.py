"""A call refused by permissions is not the tool failing (live 2026-10-12:
the new SYSTEM-level skills screen_brightness and wallpaper drew verify,
retry, strategy-change and even repair objectives from refusals by design,
twelve in an hour). Own work does not try to verify or repair what it may not
call; refusals do not count as failures; a refusal gets no learn-and-retry."""

import asyncio

from syrax import catalog, followup, limits, permissions, skillevo
from syrax import autonomy as auto
from syrax.autonomy import derive_objectives
from syrax.journal import Journal
from syrax.test_autonomy import make

REFUSED = "Error: refused: acts on the host (SYSTEM) is not done in autonomous work"


def test_only_skills_own_work_may_not_call_are_left_to_the_human(monkeypatch):
    monkeypatch.setitem(permissions.DECLARED, "wallpaper", permissions.SYSTEM)
    monkeypatch.setitem(permissions.DECLARED, "disk_usage", permissions.READ_ONLY)
    assert permissions.autonomous_refuses("wallpaper") and not permissions.autonomous_refuses("disk_usage")
    assert not permissions.autonomous_refuses("desktop")  # built-ins are refined per call


def test_no_verify_objective_for_a_skill_own_work_may_not_call(tmp_path, monkeypatch):
    monkeypatch.setitem(permissions.DECLARED, "wallpaper", permissions.SYSTEM)
    monkeypatch.setitem(permissions.DECLARED, "disk_usage", permissions.READ_ONLY)
    j, core, a = make(tmp_path, tools=["wallpaper", "disk_usage", "terminate"])
    derive_objectives(j, core.selfmodel)
    keys = {o["key"] for o in j.objectives(limit=50)}
    assert "verify-capability:disk_usage" in keys and "verify-capability:wallpaper" not in keys


def refused_call(j, t, name):
    j.record_sync("tool.started", {"id": "r", "name": name, "args": {"action": "get"}}, task_id=t)
    j.record_sync("permission.refused", {"tool": name, "level": "SYSTEM", "task_kind": "autonomous"}, task_id=t)
    j.record_sync("tool.failed", {"id": "r", "name": name, "ok": False, "refused": True, "output": REFUSED}, task_id=t)


def test_refusals_are_not_failures_of_the_tool(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.upsert_skill_sync("wallpaper", "wallpaper", str(tmp_path), "VERIFIED", evidence={})
    t = j.start_task_sync("verify wallpaper", kind="autonomous")
    for _ in range(4):
        refused_call(j, t, "wallpaper")
    j.record_sync("tool.started", {"id": "x", "name": "wallpaper", "args": {}}, task_id=t)
    j.record_sync("tool.failed", {"id": "x", "name": "wallpaper", "ok": False, "output": "wallpaper: Windows refused the wallpaper"}, task_id=t)
    use = skillevo.real_use(j)["wallpaper"]
    assert (use["uses"], use["failures"]) == (1, 1)  # the real failure counts; the four refusals do not
    assert limits.recent_tool_stats(j)["wallpaper"] == {"successes": 0, "failures": 1, "window": limits.RECENT_USES}


def test_a_refusal_gets_no_learn_and_retry(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("Verify that the `wallpaper` tool works", None, 5, "selfmodel",
                             {"kind": "tool_verified", "tool": "wallpaper"}, key="verify-capability:wallpaper")
    t = j.start_task_sync("verify wallpaper", kind="autonomous")
    refused_call(j, t, "wallpaper")
    j.record_sync("final", {"text": "refused"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    j.update_objective_sync(o["id"], status="BLOCKED", progress={"attempts_log": [{"attempt": 1, "task_id": t}]}, note="refused")
    blocked = [x for x in j.objectives(limit=10) if x["id"] == o["id"]][0]
    assert followup.derive(j, blocked) == []
    other = j.add_objective_sync("Verify that the `weather` tool works", None, 5, "selfmodel",
                                 {"kind": "tool_verified", "tool": "weather"}, key="verify-capability:weather")
    t2 = j.start_task_sync("verify weather", kind="autonomous")
    j.record_sync("final", {"text": "no idea"}, task_id=t2)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t2)
    j.update_objective_sync(other["id"], status="BLOCKED", progress={"attempts_log": [{"attempt": 1, "task_id": t2}]}, note="x")
    blocked2 = [x for x in j.objectives(limit=10) if x["id"] == other["id"]][0]
    assert [f["key"] for f in followup.derive(j, blocked2)][:1] == [f"followup:{other['id']}:learn"]  # unchanged for real failures


def test_a_broken_feature_is_reopened_even_when_other_work_is_open(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    a.set_enabled(True)
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    monkeypatch.setenv("SYRAX_FEATURES", "1")
    row = catalog.promote(j, "disk_usage", "catalog")
    j.update_objective_sync(row["id"], status="DONE", evidence={"proof": True})
    j.add_objective_sync("other work", None, 1, "human", {"kind": "tool_verified", "tool": "terminate"})
    asyncio.run(a.run_once())
    assert any(e["type"] == "objective.reopened" and e["payload"]["objective_id"] == row["id"] for e in j.recent_events(200))
