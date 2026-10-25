"""Audit 2026-10-25 ("Task runtime"): no task had a wall-clock deadline; only quality cases were cancelled, by
the quality runner. Every conversation and autonomous task now has a deadline of its kind (core.TASK_DEADLINE_S);
a task still running when it passes is cancelled with the reason, journaled task.cancelled with error_class
"deadline", and the notice says so. An eval keeps the runner's own timeouts. A task that ends in time leaves no
timer behind, and the next task runs as usual."""

import time

from syrax import core as core_mod
from syrax.test_bridge import (  # noqa: F401
    ORIGIN, TestClient, boot, call, drain_until_idle, get_journal, recv_until, reply, script, seed_interrupted, server,
)

DEADLINE_2S = "ran out of time: the task's deadline (2 s) passed"


def terminal(j, task_id):
    ev = [e for e in j.events(task_id) if e["type"] in ("task.failed", "task.cancelled")]
    assert len(ev) == 1, ev
    return ev[0]


def test_a_task_past_its_deadline_is_cancelled_with_the_reason_and_the_next_one_runs(script, monkeypatch):
    monkeypatch.setitem(core_mod.TASK_DEADLINE_S, "conversation", 2.0)
    script.queue = [call("slow", {}, cid="call_slow"), reply("Abar ready.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "wait"})
        recv_until(ws, "tool_start")
        core = core_mod.get_core()
        assert core._deadline is not None and not core._deadline.cancelled()  # armed while the task runs
        started = time.monotonic()
        seen = drain_until_idle(ws)
        assert time.monotonic() - started < 15  # the watchdog, not the 30 s tool, ended the task
        notices = [e["text"] for e in seen if e["type"] == "notice"]
        assert notices == [f"Task aborted: {DEADLINE_2S}."]
        assert any(e["type"] == "task" and e["event"] == "cancelled" and e.get("error_class") == "deadline" for e in seen)
        assert core._deadline is None  # the timer went with the task
        ws.send_json({"type": "task", "text": "abar?"})  # no stale watchdog: the next task runs to its end
        final, _ = recv_until(ws, "final")
        assert final["text"] == "Abar ready."
        drain_until_idle(ws)
        assert core._deadline is None
    j = get_journal()
    tasks = sorted(j.tasks(), key=lambda t: t["created"])
    assert [t["status"] for t in tasks] == ["CANCELLED", "SUCCESS"]
    assert tasks[0]["error"] == DEADLINE_2S
    ev = terminal(j, tasks[0]["task_id"])
    assert ev["type"] == "task.cancelled" and ev["payload"] == {"error": DEADLINE_2S, "error_class": "deadline"}
    assert not any(e["type"] in ("task.failed", "task.cancelled") for e in j.events(tasks[1]["task_id"]))


def test_a_task_that_ends_in_time_leaves_no_watchdog_behind(script, monkeypatch):
    monkeypatch.setitem(core_mod.TASK_DEADLINE_S, "conversation", 2.0)
    script.queue = [reply("quick")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "hi"})
        seen = drain_until_idle(ws)
        core = core_mod.get_core()
        assert core._deadline is None  # disarmed in _run's finally, before the idle state went out
        assert not any(e["type"] == "notice" for e in seen)
    task = get_journal().tasks()[0]
    assert task["status"] == "SUCCESS" and task["result"] == "quick"


def test_an_eval_task_is_left_to_the_quality_runners_timeouts(script, monkeypatch):
    monkeypatch.setitem(core_mod.TASK_DEADLINE_S, "conversation", 2.0)  # the kind decides, not the clock
    script.queue = [call("slow", {}, cid="call_slow")]
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws", headers=ORIGIN) as ws:
            boot(ws)
            core = core_mod.get_core()
            tid = client.portal.call(core.submit, "be slow", "be slow", None, "eval")
            recv_until(ws, "tool_start")
            assert core.busy and core.current.kind == "eval" and core._deadline is None  # no core watchdog for an eval
            time.sleep(2.5)  # past the conversation deadline: still running
            assert core.busy
            client.portal.call(core.cancel, "the quality case ran out of time (1 s)")  # the runner's own stop
            seen = drain_until_idle(ws)
    assert [e["text"] for e in seen if e["type"] == "notice"] == ["Task aborted: the quality case ran out of time (1 s)."]
    j = get_journal()
    assert j.task(tid)["status"] == "CANCELLED"
    ev = terminal(j, tid)
    assert ev["payload"] == {"error": "the quality case ran out of time (1 s)", "error_class": "quality_timeout"}


def test_a_resumed_task_gets_the_deadline_of_its_kind(script, monkeypatch, tmp_path):
    monkeypatch.setitem(core_mod.TASK_DEADLINE_S, "conversation", 2.0)
    t = seed_interrupted(tmp_path)
    script.queue = [call("slow", {}, cid="call_slow")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert hello["interrupted"][0]["task_id"] == t
        ws.send_json({"type": "resume", "task_id": t})
        recv_until(ws, "tool_start")
        core = core_mod.get_core()
        assert core._deadline is not None
        seen = drain_until_idle(ws)
        assert core._deadline is None
    assert any(e["type"] == "task" and e["event"] == "cancelled" and e.get("error_class") == "deadline" for e in seen)
    j = get_journal()
    assert j.task(t)["status"] == "CANCELLED" and j.task(t)["error"] == DEADLINE_2S


def test_the_defaults_and_the_reason_text():
    assert core_mod.TASK_DEADLINE_S == {"conversation": 1800.0, "autonomous": 5400.0, "eval": None}
    assert core_mod._span(1800.0) == "30 min" and core_mod._span(5400.0) == "90 min" and core_mod._span(2.0) == "2 s"
    assert core_mod.DEADLINE_REASON.format(span=core_mod._span(1800.0)) == "ran out of time: the task's deadline (30 min) passed"
    assert core_mod.cancel_class(core_mod.DEADLINE_REASON.format(span="30 min")) == "deadline"
