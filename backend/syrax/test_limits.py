"""Phase 1: SYRAX ranks its own limitations from evidence instead of idling."""

import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax import limits  # noqa: E402
from syrax.journal import Journal  # noqa: E402


class FakeSelf:
    def __init__(self, weaknesses=None):
        self._w = weaknesses or []

    def weaknesses(self):
        return self._w


def use(j, task, tool, ok, n, out="Error: boom"):
    for i in range(n):
        j.record_sync("tool.started", {"id": f"{tool}{ok}{i}", "name": tool, "args": {}, "step": 1}, task_id=task)
        if ok:
            j.record_sync("tool.completed", {"id": f"{tool}{ok}{i}", "name": tool, "ok": True, "output": "fine"}, task_id=task)
        else:
            j.record_sync("tool.failed", {"id": f"{tool}{ok}{i}", "name": tool, "ok": False, "output": out}, task_id=task)


def test_the_most_unreliable_busy_tool_ranks_first(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work")
    use(j, t, "str_replace_editor", True, 22)
    use(j, t, "str_replace_editor", False, 11, "Error: The path syrax\\prompt.py is not an absolute path")
    use(j, t, "python_execute", True, 39)
    use(j, t, "python_execute", False, 5)
    use(j, t, "present", False, 2)  # too few uses to judge
    ranked = limits.rank(j, FakeSelf([{"kind": "known_limitation", "detail": "no embeddings", "evidence": "docs"}]))
    assert ranked[0]["subject"] == "str_replace_editor"
    assert ranked[0]["kind"] == "tool_reliability" and "11 of its last 33" in ranked[0]["detail"]
    assert all(r["subject"] != "present" for r in ranked)
    assert all(r["subject"] != "python_execute" for r in ranked)  # 11 % is under the bar
    assert ranked[-1]["kind"] == "known_limitation"
    assert "not an absolute path" in ranked[0]["evidence"]["recent_failures"][0]["output"]


def test_choose_creates_one_planned_objective_per_week_and_journals_why(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work")
    use(j, t, "str_replace_editor", True, 10)
    use(j, t, "str_replace_editor", False, 10)
    chosen = limits.choose(j, FakeSelf())
    o = [x for x in j.objectives() if x["id"] == chosen["objective_id"]][0]
    assert o["status"] == "OPEN" and o["check_spec"]["kind"] == "tool_reliability" and o["check_spec"]["max_rate"] == 0.25
    assert len(o["evidence"]["plan"]) == 4 and o["next_action"] == o["evidence"]["plan"][0]
    assert "biggest measured limitation" in o["goal"]
    ev = [e for e in j.recent_events(50) if e["type"] == "limitation.ranked"]
    assert ev and ev[-1]["payload"]["chosen"]["objective_id"] == o["id"]
    assert limits.choose(j, FakeSelf()) is None  # the same limitation is not offered twice in one week


def test_reliability_is_judged_on_new_uses_only(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work")
    use(j, t, "str_replace_editor", False, 10)
    use(j, t, "str_replace_editor", True, 10)
    o = limits.choose(j, FakeSelf())
    obj = [x for x in j.objectives() if x["id"] == o["objective_id"]][0]
    verdict, ev = limits.judge_tool_reliability(j, obj)
    assert verdict == "RETRY" and ev["uses_since"] == 0  # old failures do not count either way
    t2 = j.start_task_sync("after the fix")
    use(j, t2, "str_replace_editor", True, 5)
    assert limits.judge_tool_reliability(j, obj)[0] == "DONE"


def test_known_limitations_are_capped_per_day(tmp_path):
    """Live: the engine researched one system-map limitation every 2 minutes."""
    j = Journal(tmp_path / "j.db")
    me = FakeSelf([{"kind": "known_limitation", "detail": f"limitation {i}", "evidence": "docs"} for i in range(6)])
    made = [limits.choose(j, me) for _ in range(6)]
    assert sum(1 for m in made if m) == limits.KNOWN_PER_DAY


def test_a_fixed_tool_stops_ranking_on_its_old_failures(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work")
    use(j, t, "str_replace_editor", False, 30)   # long ago
    use(j, t, "str_replace_editor", True, 40)    # after the fix: the latest 40 are clean
    assert all(r["subject"] != "str_replace_editor" for r in limits.rank(j, FakeSelf()))


def test_value_weighs_past_success_and_cost(tmp_path):
    """Phase 1: priority = impact x confidence / cost, all from the journal."""
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work")
    use(j, t, "str_replace_editor", True, 30)
    use(j, t, "str_replace_editor", False, 10)  # 25 % failing, ranks by score alone
    for i, status in enumerate(("BLOCKED", "BLOCKED", "BLOCKED")):  # tool fixes never worked and were expensive
        ti = j.start_task_sync(f"attempt {i}")
        for _ in range(30):
            j.record_sync("brain.answered", {"provider": "gemini"}, task_id=ti)
        o = j.add_objective_sync(f"fix tool {i}", source="selfmodel", key=f"k{i}",
                                 evidence={"limitation": {"kind": "tool_reliability", "detail": "x", "score": 0.3}})
        j.update_objective_sync(o["id"], status=status, last_task_id=ti, note="tried")
    me = FakeSelf([{"kind": "known_limitation", "detail": "no embeddings", "evidence": "docs"}])
    ranked = limits.rank(j, me)
    tool = [r for r in ranked if r["kind"] == "tool_reliability"][0]
    known = [r for r in ranked if r["kind"] == "known_limitation"][0]
    assert tool["confidence"] == 0.2 and tool["cost"] == 30.0 and known["confidence"] == 0.5
    assert tool["score"] > known["score"] and known["value"] > tool["value"] and ranked[0]["kind"] == "known_limitation"


def test_nothing_measurable_means_nothing_chosen(tmp_path):
    j = Journal(tmp_path / "j.db")
    assert limits.rank(j, FakeSelf()) == [] and limits.choose(j, FakeSelf()) is None
