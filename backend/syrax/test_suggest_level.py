"""EVOLUTION_PLAN wave 4 (direction 130 autonomy calibration): only the operator set the autonomy level, with no reading of
how SYRAX's own work had gone. The status now carries a suggested level from the last 14 days of this PC's own work; it
is a recommendation only, and 5 (self-restart) is never suggested."""

from syrax.autonomy import suggest_level
from syrax.journal import Journal


def own(j, ok, failed):
    for i in range(ok + failed):
        t = j.start_task_sync(f"own {i}", kind="autonomous")
        if i < ok:
            j.record_sync("final", {"text": "done"}, task_id=t)
            j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
        else:
            j.record_sync("task.failed", {"error": "x"}, task_id=t)


def test_too_little_evidence_keeps_the_level(tmp_path):
    j = Journal(tmp_path / "j.db")
    own(j, 5, 0)
    s = suggest_level(j, 3)
    assert s["level"] == 3 and "not enough" in s["reasons"][0]


def test_a_good_record_suggests_one_more_and_never_5(tmp_path):
    j = Journal(tmp_path / "j.db")
    own(j, 24, 1)
    assert suggest_level(j, 3)["level"] == 4
    assert suggest_level(j, 4)["level"] == 4


def test_failures_or_a_stop_suggest_one_less(tmp_path):
    j = Journal(tmp_path / "j.db")
    own(j, 8, 14)
    s = suggest_level(j, 3)
    assert s["level"] == 2 and "succeeded 8/22" in s["reasons"][0]
    j2 = Journal(tmp_path / "j2.db")
    own(j2, 25, 0)
    j2.record_sync("estop.set", {"note": "x", "by": "operator"})
    assert suggest_level(j2, 3)["level"] == 2
