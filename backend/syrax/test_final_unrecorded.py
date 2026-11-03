"""Audit 2026-11-01 (LIFE-9): when a task's terminal mark failed (twice, on a broken journal), the row stayed
IN_PROGRESS; at the next boot it came back RESUMABLE, so finished work, sends included, was offered for a re-run.
A task whose final answer is journaled but whose end is not is UNCERTAIN: finished, end not recorded."""

from syrax.journal import Journal


def test_a_finished_task_without_its_end_is_uncertain(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("say hi")
    j.record_sync("final", {"text": "hi"}, task_id=t)  # then task.completed and task.failed both failed to write
    j.close()
    j2 = Journal(tmp_path / "j.db")  # the next boot
    rec = j2.task(t)["recovery"]
    assert j2.task(t)["status"] == "INTERRUPTED" and rec["state"] == "UNCERTAIN"
    assert "final answer" in rec["checks"]["operation"]["reason"]


def test_an_unfinished_task_still_resumes(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("say hi")
    j.close()
    assert Journal(tmp_path / "j.db").task(t)["recovery"]["state"] == "RESUMABLE"
