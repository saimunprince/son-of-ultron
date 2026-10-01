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
    assert ranked[0]["kind"] == "tool_reliability" and "11 of 33" in ranked[0]["detail"]
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


def test_nothing_measurable_means_nothing_chosen(tmp_path):
    j = Journal(tmp_path / "j.db")
    assert limits.rank(j, FakeSelf()) == [] and limits.choose(j, FakeSelf()) is None
