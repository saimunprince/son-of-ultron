import time
import pytest
from pathlib import Path
from syrax.journal import Journal
from syrax.selfmodel import SelfModel
from syrax import journal as journal_mod

def test_selfmodel_durations(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    model = SelfModel(j)

    clock = [time.time() - 3600]
    monkeypatch.setattr(journal_mod, "_now", lambda: clock[0])

    for secs in (10, 30, 50):
        t = j.start_task_sync("say hi", kind="conversation")
        clock[0] += secs
        j.record_sync("final", {"text": "hi"}, task_id=t)
        j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)

    # start one more conversation task and leave it running
    j.start_task_sync("running conversation", kind="conversation")

    # start an autonomous task, add 120 s, record task.failed
    t_auto = j.start_task_sync("autonomous task", kind="autonomous")
    clock[0] += 120
    j.record_sync("task.failed", {"error": "x"}, task_id=t_auto)

    assert model.performance()["task_seconds"] == {
        "conversation": {"count": 3, "p50": 30.0, "p90": 50.0},
        "autonomous": {"count": 1, "p50": 120.0, "p90": 120.0},
    }
