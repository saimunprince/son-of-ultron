"""EVOLUTION_PLAN direction 18 (multi-objective optimization): objectives were ranked by one integer, priority, then
age. Among objectives of the same priority, the one SYRAX expects to finish (calibrate.predicted_success of its check
kind) at the lowest cost (limits.kind_stats) now goes first; priority still decides between bands, since it carries the
owner's and safety's order. The scores are on record in goal.selected."""

import asyncio

from syrax.autonomy import expected_value
from syrax.test_autonomy import make


def _history(j, kind, done, blocked):
    for i in range(done + blocked):
        o = j.add_objective_sync(f"past {kind} {i}", None, 3, "human", {"kind": kind, "path": f"/w/p{i}", "tool": "x"})
        j.update_objective_sync(o["id"], status="DONE" if i < done else "BLOCKED", note="past")


def test_same_priority_prefers_the_likelier_cheaper_goal(tmp_path):
    j, core, a = make(tmp_path)
    _history(j, "file_present", 0, 4)
    _history(j, "tool_verified", 4, 0)
    old = j.add_objective_sync("make the file", None, 2, "human", {"kind": "file_present", "path": "/w/new.md"})
    new = j.add_objective_sync("verify a tool", None, 2, "human", {"kind": "tool_verified", "tool": "desktop"})
    assert expected_value(j, old)["value"] < expected_value(j, new)["value"]
    assert a._pick()["id"] == new["id"]


def test_priority_still_wins_between_bands(tmp_path):
    j, core, a = make(tmp_path)
    _history(j, "file_present", 0, 4)
    _history(j, "tool_verified", 4, 0)
    urgent = j.add_objective_sync("make the file", None, 1, "human", {"kind": "file_present", "path": "/w/new.md"})
    j.add_objective_sync("verify a tool", None, 2, "human", {"kind": "tool_verified", "tool": "desktop"})
    assert a._pick()["id"] == urgent["id"]


def test_equal_value_keeps_age_order(tmp_path):
    j, core, a = make(tmp_path)
    first = j.add_objective_sync("one", None, 2, "human", {"kind": "tool_verified", "tool": "a"})
    j.add_objective_sync("two", None, 2, "human", {"kind": "tool_verified", "tool": "b"})
    assert a._pick()["id"] == first["id"]


def test_goal_selected_records_the_scores(tmp_path):
    j, core, a = make(tmp_path)
    o = j.add_objective_sync("verify a tool", None, 2, "human", {"kind": "tool_verified", "tool": "desktop"})
    asyncio.run(a._selected(o))
    p = [e for e in j.recent_events(50) if e["type"] == "goal.selected"][0]["payload"]
    assert set(p["expected"]) >= {"success", "cost", "value"} and "expected value" in p["rule"]
