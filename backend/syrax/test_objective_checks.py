"""Objectives that want a world change get a machine check: a release counts
only when this objective's own task committed it; a file check is a real
look at the tree, limited to the repository."""

import os
import time

from syrax import autonomy
from syrax.journal import Journal
from syrax.server import objective_check_problem


def _task_with_commit(j, goal, sha):
    t = j.start_task_sync(goal, kind="autonomous")
    j.record_sync("commit.created", {"commit": sha, "files": ["docs/x.md"], "summary": goal}, task_id=t)
    j.record_sync("final", {"text": "RELEASE COMMITTED"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    return t


def test_change_released_counts_only_this_objectives_commits(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("land the map refresh", None, 1, "human", {"kind": "change_released"})
    other = _task_with_commit(j, "someone else's release", "aaa111")
    verdict, ev = autonomy.judge(j, o, None)
    assert verdict == "RETRY" and ev["commits"] == [] and other not in ev["tasks"]
    mine = _task_with_commit(j, "the objective's own release", "bbb222")
    verdict, ev = autonomy.judge(j, o, j.task(mine))
    assert verdict == "DONE" and ev["commits"] == ["bbb222"]
    # a later judgement (re-judge, no current task) still finds it through cycle.completed
    j.record_sync("cycle.completed", {"started": time.time(), "outcome": "RAN", "objective_id": o["id"], "task_id": mine})
    verdict, ev = autonomy.judge(j, o, None)
    assert verdict == "DONE" and ev["commits"] == ["bbb222"]
    j.close()


def test_file_checks_look_at_the_tree_inside_the_repo_only(tmp_path, monkeypatch):
    monkeypatch.setattr(autonomy, "CHECK_ROOTS", (tmp_path,))
    j = Journal(tmp_path / "j.db")
    gone = tmp_path / "gone.txt"
    gone.write_text("x")
    absent = j.add_objective_sync("delete gone.txt", None, 1, "human", {"kind": "file_absent", "path": "gone.txt"})
    assert autonomy.judge(j, absent, None)[0] == "RETRY"
    gone.unlink()
    assert autonomy.judge(j, absent, None)[0] == "DONE"
    old = tmp_path / "old.txt"
    old.write_text("before")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    present = j.add_objective_sync("write old.txt", None, 1, "human", {"kind": "file_present", "path": str(old)})
    verdict, ev = autonomy.judge(j, present, None)
    assert verdict == "RETRY" and ev["exists"] is True  # it existed before the objective: no evidence of work
    old.write_text("after")
    assert autonomy.judge(j, present, None)[0] == "DONE"
    host = "C:/Windows/notepad.exe" if os.name == "nt" else "/etc/passwd"
    outside = j.add_objective_sync("touch the host", None, 1, "human", {"kind": "file_absent", "path": host})
    verdict, ev = autonomy.judge(j, outside, None)
    assert verdict == "BLOCKED" and "outside" in ev["reason"]
    assert autonomy.check_path("../../outside.txt") is None
    j.close()


def test_human_objective_checks_are_validated(monkeypatch, tmp_path):
    monkeypatch.setattr(autonomy, "CHECK_ROOTS", (tmp_path,))
    assert objective_check_problem({"kind": "change_released"}) is None
    assert objective_check_problem({"kind": "file_absent", "path": "a.txt"}) is None
    assert "needs 'path'" in objective_check_problem({"kind": "file_present"})
    assert "needs 'case'" in objective_check_problem({"kind": "quality_case_passes"})
    assert "kind must be" in objective_check_problem({"kind": "wishful"})
    assert "inside the repository" in objective_check_problem({"kind": "file_absent", "path": "../../etc/x"})
    assert "released" in autonomy._lesson({"check_spec": {"kind": "change_released"}}, {"status": "SUCCESS"}, "RETRY", {})
