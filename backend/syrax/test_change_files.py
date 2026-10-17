"""Live 2026-10-17 (objective 267): of three steps, SYRAX released step 1 alone
(09e97df, brains.py) and the objective counted as DONE, because any commit of
its own met change_released. A change_released check may name the files the
change must touch; it is met only when the objective's commits, together,
changed all of them."""

from syrax.autonomy import judge
from syrax.journal import Journal
from syrax.server import objective_check_problem

FILES = ["backend/syrax/brains.py", "backend/syrax/selfmodel.py", "backend/syrax/test_brain_ms.py"]


def commit(j, t, sha, files):
    j.record_sync("commit.created", {"commit": sha, "files": files, "summary": "x", "verification_id": 1}, task_id=t)


def test_a_part_of_the_change_is_not_done(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("Brain latency", "test", 3, "human", {"kind": "change_released", "files": FILES})
    t = j.start_task_sync("Brain latency", kind="autonomous")
    commit(j, t, "09e97df", ["backend/syrax/brains.py"])
    verdict, ev = judge(j, o, j.task(t))
    assert verdict == "RETRY" and ev["missing_files"] == FILES[1:]
    t2 = j.start_task_sync("Brain latency", kind="autonomous")
    commit(j, t2, "abc1234", ["backend/syrax/selfmodel.py", "backend/syrax/test_brain_ms.py"])
    j.record_sync("cycle.completed", {"objective_id": o["id"], "task_id": t, "outcome": "RAN"})
    verdict, ev = judge(j, o, j.task(t2))
    assert verdict == "DONE" and "missing_files" not in ev  # the two commits together touched all three


def test_without_files_any_own_commit_still_counts(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("small fix", "test", 3, "human", {"kind": "change_released"})
    t = j.start_task_sync("small fix", kind="autonomous")
    commit(j, t, "09e97df", ["backend/syrax/brains.py"])
    assert judge(j, o, j.task(t))[0] == "DONE"


def test_a_human_check_names_files_inside_the_repository():
    assert objective_check_problem({"kind": "change_released", "files": FILES}) is None
    for bad in ([], "backend/syrax/x.py", ["C:/x.py"], ["../x.py"], ["/etc/passwd"], [""]):
        assert objective_check_problem({"kind": "change_released", "files": bad}), bad
