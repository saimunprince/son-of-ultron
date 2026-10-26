"""2026-10-26: `apply_patch` ranked as SYRAX's biggest limitation with 18 of its last 40 uses failing; 8 of those
were quality cases (self_patch_stale applies a stale diff on purpose and must report the failure; another brain
diffed a file it never read), without them 10 of 40. A quality case measures the brain, and a failed case goes to
the repro hunts; it is not the tool failing or working. The ranking and the tool-reliability judge leave tasks of
kind `eval` out; conversation, autonomous and task-less uses count as before."""

from syrax import limits
from syrax.journal import Journal


class FakeSelf:
    def weaknesses(self):
        return []


def use(j, task, tool, ok, n, tag=""):
    for i in range(n):
        cid = f"{tool}{tag}{ok}{i}"
        j.record_sync("tool.started", {"id": cid, "name": tool, "args": {}, "step": 1}, task_id=task)
        if ok:
            j.record_sync("tool.completed", {"id": cid, "name": tool, "ok": True, "output": "fine"}, task_id=task)
        else:
            j.record_sync("tool.failed", {"id": cid, "name": tool, "ok": False,
                                          "output": "Error: apply_patch refused: the patch does not apply cleanly"}, task_id=task)


def test_quality_cases_are_not_the_tool_failing(tmp_path):
    j = Journal(tmp_path / "j.db")
    work = j.start_task_sync("work")
    probe = j.start_task_sync("Apply exactly this patch with apply_patch and report the result honestly", kind="eval")
    use(j, work, "apply_patch", True, 18)
    use(j, work, "apply_patch", False, 2)
    use(j, probe, "apply_patch", False, 12, tag="q")
    stats = limits.recent_tool_stats(j)["apply_patch"]
    assert stats["failures"] == 2 and stats["successes"] == 18
    assert all(r["subject"] != "apply_patch" for r in limits.rank(j, FakeSelf()))  # 10 % is under the bar


def test_a_tool_only_quality_cases_used_is_not_ranked(tmp_path):
    j = Journal(tmp_path / "j.db")
    probe = j.start_task_sync("quality case", kind="eval")
    use(j, probe, "present", False, 9)
    assert "present" not in limits.recent_tool_stats(j)
    assert limits.choose(j, FakeSelf()) is None


def test_real_work_still_ranks_a_failing_tool(tmp_path):
    j = Journal(tmp_path / "j.db")
    own = j.start_task_sync("[AUTONOMOUS OBJECTIVE] fix it", kind="autonomous")
    human = j.start_task_sync("edit my file")
    use(j, own, "apply_patch", False, 5)
    use(j, human, "apply_patch", False, 4, tag="h")
    use(j, human, "apply_patch", True, 6)
    use(j, None, "apply_patch", False, 1, tag="n")  # a task-less use still counts
    stats = limits.recent_tool_stats(j)["apply_patch"]
    assert stats["failures"] == 10 and stats["successes"] == 6
    assert limits.rank(j, FakeSelf())[0]["subject"] == "apply_patch"


def test_the_judge_counts_real_uses_after_the_objective_only(tmp_path):
    j = Journal(tmp_path / "j.db")
    obj = j.add_objective_sync("make apply_patch reliable", None, 3, "selfmodel",
                               {"kind": "tool_reliability", "tool": "apply_patch", "min_uses": 5, "max_rate": 0.25})
    probe = j.start_task_sync("self_patch_stale", kind="eval")
    work = j.start_task_sync("[AUTONOMOUS OBJECTIVE] use it", kind="autonomous")
    use(j, probe, "apply_patch", False, 6, tag="q")  # the daily quality run's stale probe, failing as designed
    use(j, work, "apply_patch", True, 5)
    verdict, ev = limits.judge_tool_reliability(j, obj)
    assert verdict == "DONE" and ev["uses_since"] == 5 and ev["failures_since"] == 0


def test_quality_successes_do_not_close_an_objective_either(tmp_path):
    j = Journal(tmp_path / "j.db")
    obj = j.add_objective_sync("make apply_patch reliable", None, 3, "selfmodel",
                               {"kind": "tool_reliability", "tool": "apply_patch", "min_uses": 5, "max_rate": 0.25})
    probe = j.start_task_sync("self_patch_edit", kind="eval")
    use(j, probe, "apply_patch", True, 8, tag="q")
    verdict, ev = limits.judge_tool_reliability(j, obj)
    assert verdict == "RETRY" and ev["uses_since"] == 0
