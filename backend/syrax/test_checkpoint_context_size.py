"""Audit 2026-11-01 (lifecycle LIFE-5, P1): every checkpoint stored the whole conversation again, so the journal grew
quadratically per task (137 MB of 193 MB). Only a task's latest checkpoint keeps its context; the earlier ones keep
everything else. A resume and repro read the latest one, so nothing they use is lost."""

from syrax.journal import Journal


def test_only_the_latest_checkpoint_keeps_the_context(tmp_path):
    j = Journal(tmp_path / "journal.db")
    t = j.start_task_sync("a long task")
    other = j.start_task_sync("another task")
    j.checkpoint_sync(other, "observed:x", context=[{"role": "user", "content": "other"}], evidence_state="SUCCESS")
    for i in range(3):
        ctx = [{"role": "user", "content": "go"}] + [{"role": "assistant", "content": f"step {k}"} for k in range(i + 1)]
        j.checkpoint_sync(t, f"observed:step{i}", completed_steps=[{"step": k} for k in range(i + 1)], context=ctx,
                          evidence_state="SUCCESS")
    cps = j.checkpoints(t)
    assert [len(c["context"] or []) for c in cps] == [0, 0, 4]
    assert [c["stage"] for c in cps] == ["observed:step0", "observed:step1", "observed:step2"]
    assert len(cps[0]["completed_steps"]) == 1  # the rest of an earlier checkpoint stays
    assert len(j.latest_checkpoint(t)["context"]) == 4
    assert len(j.latest_checkpoint(other)["context"]) == 1  # another task is untouched
