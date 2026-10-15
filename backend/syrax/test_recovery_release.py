"""Live 2026-10-15: SYRAX stopped while its own release was gating (objective
224, attempt 5), and recovery left the task UNCERTAIN for a human. A release
commits only after its gate passes, so the journal and git decide: a journaled
commit is COMPLETED; no commit with HEAD unmoved is NOT_STARTED (nothing landed,
the task can resume); no journaled commit while HEAD moved stays UNCERTAIN."""

from syrax.journal import Journal


def op():
    return {"id": "o1", "name": "release", "args": {"summary": "expire stale inferences"}, "step": 11}


def test_a_release_that_never_committed_with_head_unmoved_did_not_start(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("objective 224", kind="autonomous")
    v = j.verify_operation(op(), task_id=t, head_unchanged=True)
    assert v["state"] == "NOT_STARTED" and "nothing landed" in v["checks"]["reason"]


def test_a_journaled_commit_means_the_release_completed(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("objective 224", kind="autonomous")
    j.record_sync("commit.created", {"commit": "abc1234def", "files": {"backend/syrax/memory.py": "M"}}, task_id=t)
    v = j.verify_operation(op(), task_id=t, head_unchanged=False)
    assert v["state"] == "COMPLETED" and v["checks"]["commit"] == "abc1234def"


def test_no_commit_but_a_moved_head_is_for_a_human(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("objective 224", kind="autonomous")
    assert j.verify_operation(op(), task_id=t, head_unchanged=False)["state"] == "UNCERTAIN"
    assert j.verify_operation(op(), task_id=t, head_unchanged=None)["state"] == "UNCERTAIN"
    assert j.verify_operation(op())["state"] == "UNCERTAIN"  # without the task, nothing to check: as before
