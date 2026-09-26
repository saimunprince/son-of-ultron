"""Durable journal tests: transactions, transition table, truthfulness guard,
semantic checkpoints, SIGKILL crash matrix, idempotent recovery, resume.

No server, no LLM, no network. Child processes for crash tests import only
syrax.journal (stdlib), so they are cheap.
"""

import asyncio
import json
import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from syrax.journal import (
    STATUSES,
    TERMINAL,
    TRANSITIONS,
    Journal,
    JournalError,
    _bound_context,
)

BACKEND = Path(__file__).resolve().parents[1]


def new(tmp_path, **kw) -> Journal:
    return Journal(tmp_path / "journal.db", **kw)


def types(j: Journal, task_id: str):
    return [e["type"] for e in j.events(task_id)]


# ——— storage basics ———


def test_open_sets_wal_full_sync_and_private_mode(tmp_path):
    j = new(tmp_path)
    assert j.pragma("journal_mode") == "wal"
    assert j.pragma("synchronous") == 2  # FULL
    assert oct(os.stat(tmp_path / "journal.db").st_mode & 0o777) == "0o600"
    j.close()


def test_events_get_per_task_seq_and_taskless_seq_zero(tmp_path):
    j = new(tmp_path)
    a = j.start_task_sync("a")
    b = j.start_task_sync("b")
    j.record_sync("think", {"step": 1}, task_id=a)
    j.record_sync("think", {"step": 1}, task_id=b)
    j.record_sync("think", {"step": 2}, task_id=a)
    ev = j.record_sync("recovery.started", {"boot_id": "x"})
    assert [e["seq"] for e in j.events(a)] == [1, 2, 3]
    assert [e["seq"] for e in j.events(b)] == [1, 2]
    assert ev.seq == 0 and ev.task_id is None


def test_task_row_changes_in_same_transaction_as_event(tmp_path):
    j = new(tmp_path)
    t = j.start_task_sync("edit file")
    ev = j.record_sync("think", {"step": 3, "content": "x"}, task_id=t)
    row = j.task(t)
    assert row["current_step"] == 3 and row["stage"] == "thinking" and row["last_event_id"] == ev.id
    ev2 = j.record_sync(
        "tool.started", {"id": "c1", "name": "python_execute", "args": {"code": "1"}, "step": 3}, task_id=t
    )
    row = j.task(t)
    assert row["stage"] == "tool:python_execute"
    assert row["operation"]["name"] == "python_execute" and row["operation"]["id"] == "c1"
    assert row["last_event_id"] == ev2.id
    j.record_sync("tool.completed", {"id": "c1", "name": "python_execute", "ok": True, "output": "1"}, task_id=t)
    assert j.task(t)["operation"] is None and j.task(t)["stage"] == "observed:python_execute"


def test_unknown_task_is_refused(tmp_path):
    j = new(tmp_path)
    with pytest.raises(JournalError):
        j.record_sync("think", {}, task_id="nope")


# ——— truthfulness + transition table ———


def test_success_requires_final_event_and_rolls_back(tmp_path):
    j = new(tmp_path)
    t = j.start_task_sync("say hi")
    j.record_sync("think", {"step": 1}, task_id=t)
    before = j.count("events")
    with pytest.raises(JournalError, match="no evidence"):
        j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    assert j.task(t)["status"] == "IN_PROGRESS"
    assert j.count("events") == before  # the refused event was rolled back
    j.record_sync("final", {"text": ""}, task_id=t)  # empty final is not evidence either
    with pytest.raises(JournalError):
        j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    j.record_sync("final", {"text": "hi"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    assert j.task(t)["status"] == "SUCCESS" and j.task(t)["result"] == "hi"


def test_task_completed_rejects_other_statuses(tmp_path):
    j = new(tmp_path)
    t = j.start_task_sync("x")
    j.record_sync("final", {"text": "ok"}, task_id=t)
    with pytest.raises(JournalError):
        j.record_sync("task.completed", {"status": "FAILED"}, task_id=t)


def test_terminal_task_rejects_further_events_except_verification(tmp_path):
    j = new(tmp_path)
    t = j.start_task_sync("x")
    j.record_sync("task.failed", {"error": "boom"}, task_id=t)
    assert j.task(t)["status"] == "FAILED" and j.task(t)["error"] == "boom"
    for kind in ("think", "tool.started", "final", "task.completed", "task.cancelled"):
        with pytest.raises(JournalError):
            j.record_sync(kind, {"status": "SUCCESS", "text": "x"}, task_id=t)
    ev = j.record_verification_sync({"status": "BLOCKED", "gates": [{"name": "pytest", "status": "FAIL", "required": True}]}, task_id=t)
    assert ev.type == "verification.completed"
    assert j.task(t)["status"] == "FAILED"


EVENT_FOR = {
    "IN_PROGRESS": ("answer", {}),
    "BLOCKED": ("ask", {"question": "?"}),
    "SUCCESS": ("task.completed", {"status": "SUCCESS"}),
    "PARTIAL": ("task.completed", {"status": "PARTIAL"}),
    "FAILED": ("task.failed", {"error": "e"}),
    "CANCELLED": ("task.cancelled", {}),
    "INTERRUPTED": ("task.interrupted", {"error": "i"}),
    "UNKNOWN": ("task.unknown", {"error": "u"}),
}


def _task_in_state(j: Journal, state: str) -> str:
    """Drive a fresh task into ``state`` through legal transitions only."""
    if state == "PENDING":
        return j.start_task_sync("p", pending=True)
    t = j.start_task_sync("p")
    j.record_sync("final", {"text": "done"}, task_id=t)
    if state == "IN_PROGRESS":
        return t
    if state in ("SUCCESS", "PARTIAL", "FAILED", "CANCELLED", "INTERRUPTED", "BLOCKED"):
        j.record_sync(*EVENT_FOR[state], task_id=t)
        return t
    if state == "UNKNOWN":
        j.record_sync("task.interrupted", {"error": "i"}, task_id=t)
        j.record_sync("task.unknown", {"error": "u"}, task_id=t)
        return t
    raise AssertionError(state)


@pytest.mark.parametrize("src", STATUSES)
@pytest.mark.parametrize("dst", [s for s in STATUSES if s != "PENDING"])
def test_transition_table_is_enforced(tmp_path, src, dst):
    j = new(tmp_path)
    t = _task_in_state(j, src)
    assert j.task(t)["status"] == src
    kind, payload = EVENT_FOR[dst]
    if dst == "IN_PROGRESS" and src == "INTERRUPTED":
        kind, payload = "recovery.resumed", {"boot_id": "b2"}
    if dst == "IN_PROGRESS" and src == "PENDING":
        kind, payload = "task.started", {}
    allowed = (src == dst and src not in TERMINAL) or dst in TRANSITIONS[src]
    if allowed:
        j.record_sync(kind, payload, task_id=t)
        assert j.task(t)["status"] == dst
    else:
        with pytest.raises(JournalError):
            j.record_sync(kind, payload, task_id=t)
        assert j.task(t)["status"] == src


def test_ask_blocks_and_answer_or_tool_result_unblocks(tmp_path):
    j = new(tmp_path)
    t = j.start_task_sync("x")
    j.record_sync("tool.started", {"id": "a1", "name": "ask_human", "args": {"inquire": "which?"}}, task_id=t)
    j.record_sync("ask", {"question": "which?"}, task_id=t)
    assert j.task(t)["status"] == "BLOCKED" and j.task(t)["stage"] == "asking"
    j.record_sync("answer", {"text": "this"}, task_id=t)
    assert j.task(t)["status"] == "IN_PROGRESS"
    j.record_sync("ask", {"question": "sure?"}, task_id=t)
    j.record_sync("tool.completed", {"id": "a1", "name": "ask_human", "ok": True, "output": "timed out"}, task_id=t)
    assert j.task(t)["status"] == "IN_PROGRESS"


def test_pending_task_lifecycle(tmp_path):
    j = new(tmp_path)
    t = j.start_task_sync("later", pending=True)
    assert j.task(t)["status"] == "PENDING" and types(j, t) == ["task.queued"]
    with pytest.raises(JournalError):
        j.record_sync("task.failed", {"error": "x"}, task_id=t)
    j.record_sync("task.started", {}, task_id=t)
    assert j.task(t)["status"] == "IN_PROGRESS"


# ——— checkpoints ———


def test_checkpoint_row_and_event_are_atomic_and_bound(tmp_path):
    j = new(tmp_path)
    t = j.start_task_sync("x")
    ctx = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "x" * 20000}]
    ev = j.checkpoint_sync(
        t, "observed:python_execute",
        completed_steps=[{"step": 1, "tool": "python_execute", "ok": True}],
        verified={"tests": "NOT_VERIFIED"}, next_action="reply", context=ctx, evidence_state="SUCCESS",
    )
    row = j.task(t)
    cp = j.latest_checkpoint(t)
    assert cp is not None and row["last_checkpoint_id"] == cp["id"] == ev.payload["checkpoint_id"]
    assert cp["completed_steps"][0]["tool"] == "python_execute"
    assert cp["env"]["boot_id"] == j.boot_id and "git_head" in cp["env"]
    assert cp["context"][1]["content"].endswith("…[truncated]")
    assert types(j, t) == ["task.started", "checkpoint.created"]
    with pytest.raises(JournalError):
        j.checkpoint_sync(t, "x", evidence_state="MAYBE")
    j.record_sync("task.failed", {"error": "e"}, task_id=t)
    with pytest.raises(JournalError):
        j.checkpoint_sync(t, "late")
    assert j.count("checkpoints") == 1


def test_bound_context_never_orphans_tool_results():
    big = "y" * 7000
    msgs = [{"role": "user", "content": big}]
    for i in range(40):
        msgs.append({"role": "assistant", "tool_calls": [{"id": f"c{i}", "function": {"name": "t", "arguments": "{}"}}], "content": big})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": big})
    out = _bound_context(msgs)
    assert out and out[0]["role"] != "tool"
    assert len(json.dumps(out)) <= 200_000 + 20_000


# ——— crash matrix ———

CHILD = r"""
import os, signal, sys, json
from syrax.journal import Journal
db, point = sys.argv[1], sys.argv[2]
j = Journal(db, boot_id="child", recover=False)
t = j.start_task_sync("crash test", session_id="s")
print(t, flush=True)
def die():
    os.kill(os.getpid(), signal.SIGKILL)
if point == "after_start":
    die()
for i in range(1, 6):
    j.record_sync("think", {"step": i, "content": f"t{i}"}, task_id=t)
if point == "after_thinks":
    die()
if point == "mid_txn":
    cur = j._db.cursor()
    cur.execute("BEGIN IMMEDIATE")
    cur.execute("INSERT INTO events(ts, task_id, type, payload, seq) VALUES (0, ?, 'think', '{}', 99)", (t,))
    cur.execute("UPDATE tasks SET current_step=99 WHERE task_id=?", (t,))
    die()
op = json.loads(os.environ.get("CRASH_OP") or "null") or {"id": "c1", "name": "python_execute", "args": {"code": "print(1)"}, "step": 5}
j.record_sync("tool.started", op, task_id=t)
if point == "after_tool_started":
    die()
j.record_sync("tool.completed", {"id": op["id"], "name": op["name"], "ok": True, "output": "1"}, task_id=t)
j.checkpoint_sync(t, "observed:" + op["name"], completed_steps=[{"step": 5, "tool": op["name"], "ok": True}], context=[{"role": "user", "content": "crash test"}], evidence_state="SUCCESS")
if point == "after_checkpoint":
    die()
j.record_sync("final", {"text": "done"}, task_id=t)
j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
print("completed", flush=True)
"""


def crash(tmp_path, point: str, op: dict | None = None) -> str:
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    if op:
        env["CRASH_OP"] = json.dumps(op)
    proc = subprocess.run(
        [sys.executable, "-c", CHILD, str(tmp_path / "journal.db"), point],
        cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == -signal.SIGKILL, proc.stderr
    return proc.stdout.split()[0]


@pytest.mark.parametrize(
    "point,expected_types,step,op",
    [
        ("after_start", ["task.started"], 0, None),
        ("after_thinks", ["task.started"] + ["think"] * 5, 5, None),
        ("mid_txn", ["task.started"] + ["think"] * 5, 5, None),
        ("after_tool_started", ["task.started"] + ["think"] * 5 + ["tool.started"], 5, "python_execute"),
        ("after_checkpoint", ["task.started"] + ["think"] * 5 + ["tool.started", "tool.completed", "checkpoint.created"], 5, None),
    ],
)
def test_sigkill_keeps_exactly_the_committed_state(tmp_path, point, expected_types, step, op):
    t = crash(tmp_path, point)
    j = new(tmp_path, recover=False)
    assert types(j, t) == expected_types
    row = j.task(t)
    assert row["status"] == "IN_PROGRESS" and row["current_step"] == step
    assert (row["operation"] or {}).get("name") == op
    assert row["last_event_id"] == j.events(t)[-1]["id"]  # never points at a lost event


def test_recovery_after_crash_marks_interrupted_with_verified_reality(tmp_path):
    t = crash(tmp_path, "after_tool_started")
    j = new(tmp_path)  # new boot: recovery runs
    assert [r["task_id"] for r in j.recovered] == [t]
    r = j.recovered[0]
    assert r["last_step"] == 5 and r["tool"] == "python_execute"
    assert r["recovery"]["state"] == "UNCERTAIN"  # python side effects unknowable
    assert r["recovery"]["operation_state"] == "UNCERTAIN"
    assert r["recovery"]["checks"]["journal_consistent"] is True
    assert r["recovery"]["resume_from"] == "goal"
    row = j.task(t)
    assert row["status"] == "INTERRUPTED" and "step 5" in row["error"] and row["recovery"]["state"] == "UNCERTAIN"
    assert types(j, t)[-2:] == ["recovery.verified", "task.interrupted"]
    taskless = [e["type"] for e in j.recent_events() if e["task_id"] is None]
    assert taskless == ["recovery.started", "recovery.completed"]


def test_recovery_after_checkpoint_is_resumable_from_checkpoint(tmp_path):
    t = crash(tmp_path, "after_checkpoint")
    j = new(tmp_path)
    rec = j.task(t)["recovery"]
    assert rec["state"] == "RESUMABLE" and rec["operation_state"] == "NONE"
    assert rec["resume_from"].startswith("checkpoint:")
    ctx = j.resume_context(t)
    assert ctx["checkpoint"]["context"][0]["content"] == "crash test"
    assert ctx["checkpoint"]["completed_steps"][0]["tool"] == "python_execute"


@pytest.mark.parametrize(
    "prepare,expected_op,expected_state",
    [
        (lambda p: p.write_text("hello"), "COMPLETED", "RESUMABLE"),
        (lambda p: None, "NOT_STARTED", "RESUMABLE"),
        (lambda p: p.write_text("half"), "PARTIAL", "UNCERTAIN"),
    ],
)
def test_recovery_checks_file_edits_against_the_filesystem(tmp_path, prepare, expected_op, expected_state):
    target = tmp_path / "out.txt"
    op = {"id": "e1", "name": "str_replace_editor", "args": {"command": "create", "path": str(target), "file_text": "hello"}, "step": 5}
    t = crash(tmp_path, "after_tool_started", op)
    prepare(target)
    j = new(tmp_path)
    rec = j.task(t)["recovery"]
    assert rec["operation_state"] == expected_op and rec["state"] == expected_state
    assert rec["checks"]["operation"]["exists"] == target.exists()


def test_recovery_of_str_replace_detects_applied_edit(tmp_path):
    j = new(tmp_path)
    f = tmp_path / "m.py"
    f.write_text("a = 1\nb = 2\n")
    op = {"name": "str_replace_editor", "args": {"command": "str_replace", "path": str(f), "old_str": "a = 1\n", "new_str": "a = 10\n"}}
    assert j.verify_operation(op)["state"] == "NOT_STARTED"
    f.write_text("a = 10\nb = 2\n")
    assert j.verify_operation(op)["state"] == "COMPLETED"
    f.write_text("a = 1\na = 10\n")
    assert j.verify_operation(op)["state"] == "UNCERTAIN"  # both old and new present: ambiguous
    assert j.verify_operation({"name": "ask_human", "args": {"inquire": "q"}})["state"] == "BLOCKED"
    assert j.verify_operation(None)["state"] == "NONE"


def test_blocked_task_recovers_as_blocked(tmp_path):
    j = new(tmp_path, boot_id="old")
    t = j.start_task_sync("x")
    j.record_sync("tool.started", {"id": "a", "name": "ask_human", "args": {"inquire": "which folder?"}}, task_id=t)
    j.record_sync("ask", {"question": "which folder?"}, task_id=t)
    j.close()
    j2 = new(tmp_path, boot_id="new")
    assert j2.recovered[0]["question"] == "which folder?"
    assert j2.task(t)["recovery"]["state"] == "BLOCKED" and j2.task(t)["status"] == "INTERRUPTED"


def test_recovery_is_idempotent_across_reruns_and_boots(tmp_path):
    t = crash(tmp_path, "after_thinks")
    j = new(tmp_path)
    assert len(j.recovered) == 1
    n_events, n_tasks = j.count("events"), j.count("tasks")
    assert j.recover_interrupted() == []  # same boot, again
    j.close()
    j3 = new(tmp_path)  # another boot
    assert j3.recovered == []
    assert (j3.count("events"), j3.count("tasks")) == (n_events, n_tasks)
    assert j3.task(t)["status"] == "INTERRUPTED"


def test_recovery_skips_tasks_of_the_current_boot(tmp_path):
    j = new(tmp_path)
    t = j.start_task_sync("mine")
    assert j.recover_interrupted() == []
    assert j.task(t)["status"] == "IN_PROGRESS"


def test_crash_inside_recovery_loses_nothing_and_next_boot_redoes_it(tmp_path):
    t = crash(tmp_path, "after_thinks")
    j = new(tmp_path, recover=False)
    n = j.count("events")
    j.close()

    def boom(where):
        raise KeyboardInterrupt(where)  # simulate the process dying inside the txn

    Journal._crash_hook = staticmethod(boom)
    try:
        with pytest.raises(KeyboardInterrupt):
            new(tmp_path)
    finally:
        Journal._crash_hook = None
    j2 = new(tmp_path, recover=False)
    assert j2.count("events") == n and j2.task(t)["status"] == "IN_PROGRESS"  # rolled back
    j2.close()
    j3 = new(tmp_path)
    assert len(j3.recovered) == 1 and j3.task(t)["status"] == "INTERRUPTED"
    assert [e["type"] for e in j3.recent_events() if e["task_id"] is None] == ["recovery.started", "recovery.completed"]


def test_uncommitted_rows_from_a_killed_process_are_invisible(tmp_path):
    t = crash(tmp_path, "mid_txn")
    con = sqlite3.connect(tmp_path / "journal.db")
    assert con.execute("SELECT COUNT(*) FROM events WHERE seq=99").fetchone()[0] == 0
    assert con.execute("SELECT current_step FROM tasks WHERE task_id=?", (t,)).fetchone()[0] == 5


# ——— resume ———


def test_resume_context_and_mark_resumed(tmp_path):
    t = crash(tmp_path, "after_checkpoint")
    j = new(tmp_path)
    with pytest.raises(JournalError):
        j.resume_context("nope")
    ctx = j.resume_context(t)
    assert ctx["task"]["status"] == "INTERRUPTED" and ctx["recovery"]["state"] == "RESUMABLE"
    ev = j.mark_resumed_sync(t, session_id="s9")
    assert ev.type == "recovery.resumed" and ev.wire()["type"] == "recovery" and ev.wire()["event"] == "resumed"
    row = j.task(t)
    assert row["status"] == "IN_PROGRESS" and row["boot_id"] == j.boot_id and row["session_id"] == "s9"
    with pytest.raises(JournalError):
        j.resume_context(t)  # no longer interrupted
    assert j.recover_interrupted() == []  # it belongs to this boot now
    j.record_sync("final", {"text": "finished"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    assert j.task(t)["status"] == "SUCCESS"


# ——— fan-out and wire format ———


def test_async_record_fans_out_wire_events_and_volatile_is_not_stored(tmp_path):
    j = new(tmp_path)
    seen = []

    async def sub(ev):
        seen.append(ev.wire())

    async def go():
        j.subscribe(sub)
        t = await j.start_task("x")
        await j.record("tool.started", {"id": "c", "name": "desktop", "args": {"action": "screenshot"}}, task_id=t)
        await j.record(
            "tool.completed", {"id": "c", "name": "desktop", "ok": True, "output": "png"},
            task_id=t, volatile={"image": "QUJD"},
        )
        await j.record("brain.failover", {"provider": "gemini", "reason": "429"}, task_id=t)
        await j.record("final", {"text": "ok"}, task_id=t)
        await j.record("task.completed", {"status": "SUCCESS"}, task_id=t)
        return t

    t = asyncio.run(go())
    kinds = [(e["type"], e.get("event")) for e in seen]
    assert kinds == [("task", "started"), ("tool_start", None), ("tool_result", None), ("brain", "failover"), ("final", None), ("task", "completed")]
    assert seen[2]["image"] == "QUJD" and seen[2]["task_id"] == t and "event_id" in seen[2]
    stored = [e for e in j.events(t) if e["type"] == "tool.completed"][0]
    assert "image" not in stored["payload"]


def test_failing_subscriber_does_not_break_the_journal(tmp_path):
    j = new(tmp_path)

    async def bad(ev):
        raise RuntimeError("ui died")

    async def go():
        j.subscribe(bad)
        t = await j.start_task("x")
        await j.record("think", {"step": 1}, task_id=t)
        return t

    t = asyncio.run(go())
    assert types(j, t) == ["task.started", "think"]


# ——— queries + verification records ———


def test_queries_respect_limits_and_status_filter(tmp_path):
    j = new(tmp_path)
    ids = [j.start_task_sync(f"t{i}") for i in range(5)]
    j.record_sync("task.failed", {"error": "x"}, task_id=ids[0])
    assert [t["goal"] for t in j.tasks(limit=2)] == ["t4", "t3"]
    assert [t["task_id"] for t in j.tasks(status="FAILED")] == [ids[0]]
    assert [t["task_id"] for t in j.tasks(status=["FAILED", "IN_PROGRESS"], limit=10)] == ids[::-1]
    for i in range(3):
        j.record_sync("think", {"step": i}, task_id=ids[1])
    assert len(j.events(ids[1], limit=2)) == 2
    first = j.events(ids[1])[0]["id"]
    assert [e["type"] for e in j.events(ids[1], after_id=first)] == ["think"] * 3


def test_verification_record_is_stored_with_evidence(tmp_path):
    j = new(tmp_path)
    ev = j.record_verification_sync(
        {"status": "GREEN", "git_head": "abc", "gates": [{"name": "pytest", "status": "PASS", "required": True, "evidence": "43 passed"}]}
    )
    assert ev.wire()["type"] == "verification" and ev.wire()["status"] == "GREEN"
    rows = j.verifications()
    assert rows[0]["status"] == "GREEN" and rows[0]["gates"][0]["evidence"] == "43 passed"
    ev2 = j.record_verification_sync({"status": "nonsense", "gates": []})
    assert ev2.payload["status"] == "BLOCKED"  # anything but GREEN is BLOCKED


def test_write_failure_raises_and_leaves_db_consistent(tmp_path):
    j = new(tmp_path)
    t = j.start_task_sync("x")
    j._db.close()  # simulate the database going away
    with pytest.raises(sqlite3.Error):
        j.record_sync("think", {"step": 1}, task_id=t)
    j2 = new(tmp_path, recover=False)
    assert types(j2, t) == ["task.started"] and j2.task(t)["status"] == "IN_PROGRESS"


# ——— observer queries: replay + WHY ———


def test_events_between_and_task_detail(tmp_path):
    j = new(tmp_path)
    t0 = __import__("time").time()
    t = j.start_task_sync("explain")
    j.record_sync("tool.started", {"id": "c", "name": "python_execute", "args": {"code": "1"}, "step": 1}, task_id=t)
    j.record_sync("tool.completed", {"id": "c", "name": "python_execute", "ok": True, "output": "1"}, task_id=t)
    j.checkpoint_sync(t, "observed:python_execute", completed_steps=[{"step": 1}], context=[{"role": "user", "content": "x"}])
    j.record_sync("final", {"text": "done"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    o = j.add_objective_sync("obj", key="k")
    j.update_objective_sync(o["id"], status="DONE", last_task_id=t, note="met")
    window = j.events_between(t0)
    assert [e["type"] for e in window][:2] == ["task.started", "tool.started"]
    assert any(e["task_id"] is None and e["type"] == "objective.created" for e in window)
    assert j.events_between(t0, t0) == [] and j.events_between(__import__("time").time() + 10) == []
    d = j.task_detail(t)
    assert d["task"]["status"] == "SUCCESS"
    assert [e["type"] for e in d["events"]][0] == "task.started"
    assert d["checkpoints"][0]["stage"] == "observed:python_execute" and d["checkpoints"][0]["context_messages"] == 1
    assert "context" not in d["checkpoints"][0]
    assert d["objective"]["id"] == o["id"] and d["objective"]["status"] == "DONE"
    assert j.task_detail("nope") is None
