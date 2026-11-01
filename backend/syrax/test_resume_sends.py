"""Audit 2026-11-01 (lifecycle LIFE-1, LIFE-2, confirmed): (1) a send that finished after the task's last checkpoint
left the task RESUMABLE; a resume starts from that checkpoint's context, which does not hold the send, so the model
would send it again. (2) A send left open by an earlier step (it timed out and the task went on) made no difference
when the crash came during another, harmless call. Both are UNCERTAIN now, and a resume holds the same send."""

import time

from syrax.journal import Journal

SEND = {"tool": "send_message", "args_hash": "h1", "summary": "send_message to Bob: hi", "step": 2}


def crashed_after(tmp_path, events):
    j = Journal(tmp_path / "journal.db")
    t = j.start_task_sync("tell Bob hi")
    j.checkpoint_sync(t, "observed:self_inspect", context=[{"role": "user", "content": "tell Bob hi"}], evidence_state="SUCCESS")
    time.sleep(0.01)
    for type_, payload in events:
        j.record_sync(type_, payload, task_id=t)
    j.close()
    return t


def recovered(tmp_path, t):
    j = Journal(tmp_path / "journal.db")  # a new boot: recovery runs
    return j, next(r for r in j.recovered if r["task_id"] == t)["recovery"]


def test_a_send_done_after_the_last_checkpoint_is_uncertain_and_held_on_resume(tmp_path):
    t = crashed_after(tmp_path, [
        ("tool.started", {"id": "c1", "name": "send_message", "args": {"to": "Bob"}, "step": 2}),
        ("intent.recorded", SEND),
        ("intent.done", {"tool": "send_message", "args_hash": "h1", "ok": True}),
        ("tool.completed", {"id": "c1", "name": "send_message", "ok": True, "output": "sent"}),
    ])
    j, rec = recovered(tmp_path, t)
    assert rec["state"] == "UNCERTAIN", rec
    assert rec["intent"]["summary"] == "send_message to Bob: hi" and "after the last checkpoint" in rec["checks"]["operation"]["reason"]
    assert [i["args_hash"] for i in j.done_intents(t)] == ["h1"]


def test_an_open_send_from_an_earlier_step_makes_a_harmless_crash_uncertain(tmp_path):
    t = crashed_after(tmp_path, [
        ("tool.started", {"id": "c1", "name": "send_message", "args": {"to": "Bob"}, "step": 2}),
        ("intent.recorded", SEND),
        ("tool.failed", {"id": "c1", "name": "send_message", "ok": False, "output": "timed out"}),
        ("tool.started", {"id": "c2", "name": "self_inspect", "args": {}, "step": 3}),
    ])
    _, rec = recovered(tmp_path, t)
    assert rec["state"] == "UNCERTAIN" and rec["intent"]["tool"] == "send_message", rec


def test_a_send_that_said_it_did_not_happen_and_a_plain_task_stay_resumable(tmp_path):
    t = crashed_after(tmp_path, [
        ("tool.started", {"id": "c1", "name": "send_message", "args": {"to": "Bob"}, "step": 2}),
        ("intent.recorded", SEND),
        ("intent.done", {"tool": "send_message", "args_hash": "h1", "ok": False}),
        ("tool.failed", {"id": "c1", "name": "send_message", "ok": False, "output": "Error: recipient not found"}),
        ("tool.started", {"id": "c2", "name": "self_inspect", "args": {}, "step": 3}),
    ])
    _, rec = recovered(tmp_path, t)
    assert rec["state"] == "RESUMABLE", rec
