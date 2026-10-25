"""Milestone 1 of the evolution mission (2026-10-25): a human request made while SYRAX works is queued, not dropped.
Until now every such request was answered "Already executing. Stop it first." and lost (voice and HUD included);
the journal's PENDING status had waited unused. A client that asks to queue (`task {queue: true}`) gets a PENDING
task that starts when the running one ends, oldest first; SYRAX's own work never queues; the autonomy cycle
waits while a human request is in the queue; queued requests survive a restart unless they are stale."""

import asyncio
import time

from syrax.test_bridge import (  # noqa: F401
    ORIGIN, TestClient, boot, call, core_mod, drain_until_idle, recv_until, reply, script, server,
)


def test_a_request_made_while_busy_is_queued_and_runs_next(script):
    script.queue = [
        call("python_execute", {"code": "import time; time.sleep(1); print('first')"}),
        reply("First done."),
        reply("Second done."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert hello["queue"] == []
        ws.send_json({"type": "task", "text": "first job"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "task", "text": "second job", "queue": True})
        notice, seen = recv_until(ws, "notice")
        assert notice["text"].startswith("Queued (position 1)")
        assert notice["action"]["msg"] == {"type": "queue_cancel", "task_id": notice["action"]["msg"]["task_id"]}
        assert any(e["type"] == "queue" and [i["goal"] for i in e["items"]] == ["second job"] for e in seen)
        first, _ = recv_until(ws, "final")
        assert first["text"] == "First done."
        second, seen = recv_until(ws, "final")
        assert second["text"] == "Second done."
        assert any(e["type"] == "notice" and e["text"].startswith("Queued request starting") for e in seen)
        drain_until_idle(ws)
    j = core_mod.get_core().journal
    row = next(r for r in j.tasks(limit=5) if r["goal"] == "second job")
    assert row["status"] == "SUCCESS" and row["result"] == "Second done."
    assert [e["type"] for e in j.events(row["task_id"])][:2] == ["task.queued", "task.started"]
    assert not script.queue


def test_the_queue_is_listed_and_a_waiting_request_can_be_removed(script):
    script.queue = [call("slow", {}, cid="call_slow")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "wait"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "task", "text": "later please", "queue": True})
        recv_until(ws, "notice")
        ws.send_json({"type": "queue"})
        q, _ = recv_until(ws, "queue")
        assert [i["goal"] for i in q["items"]] == ["later please"] and q["items"][0]["position"] == 1
        ws.send_json({"type": "queue_cancel", "task_id": q["items"][0]["task_id"], "note": "changed my mind"})
        q2, _ = recv_until(ws, "queue")
        assert q2["items"] == []
        ws.send_json({"type": "queue_cancel", "task_id": "nope"})
        n, _ = recv_until(ws, "notice")
        assert "No such queued request" in n["text"]
        ws.send_json({"type": "stop"})
        drain_until_idle(ws)
    j = core_mod.get_core().journal
    row = next(r for r in j.tasks(limit=5) if r["goal"] == "later please")
    assert row["status"] == "CANCELLED" and "changed my mind" in row["error"]
    assert script.queue == []  # the slow call was consumed; nothing ran for the removed request


def test_without_the_queue_flag_a_busy_core_still_refuses(script):
    script.queue = [call("slow", {}, cid="call_slow")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "wait"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "task", "text": "me too"})
        n, _ = recv_until(ws, "notice")
        assert "Already executing" in n["text"]
        assert core_mod.get_core().queued() == []
        ws.send_json({"type": "stop"})
        drain_until_idle(ws)


def test_syraxs_own_work_never_queues(script):
    script.queue = [call("slow", {}, cid="call_slow")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)  # builds the agent (with the slow tool)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit("wait", said="wait", session_id=None, kind="conversation")
        assert tid
        own = await core.submit("own work", said=None, session_id=None, kind="autonomous", queue=True)
        case = await core.submit("a case", said="a case", session_id=None, kind="eval", queue=True)
        waiting = core.queued()
        await core.cancel("test over")
        await core.wait()
        return own, case, waiting

    assert asyncio.run(go()) == (None, None, [])


def test_the_cycle_waits_while_a_human_request_is_queued(script, monkeypatch):
    core = core_mod.get_core()
    monkeypatch.setattr(core, "queued", lambda: [{"task_id": "x", "goal": "hi", "created": 0, "position": 1}])
    rep = asyncio.run(core.autonomy.run_once(force=True))
    assert rep.outcome == "BUSY" and "human request" in rep.reason


def test_queued_requests_survive_a_restart_young_ones_start_stale_ones_are_cancelled(script):
    script.queue = [reply("Fresh one answered.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    j = core.journal
    stale = j.start_task_sync("old wish", kind="conversation", pending=True)
    young = j.start_task_sync("fresh wish", kind="conversation", pending=True)
    with j._txn() as cur:
        cur.execute("UPDATE tasks SET created=? WHERE task_id=?", (time.time() - 7200, stale))

    async def go():
        out = await core.requeue_after_boot()
        await core.wait()
        return out

    out = asyncio.run(go())
    assert out == {"kept": [young], "dropped": [stale], "started": young}
    assert j.task(stale)["status"] == "CANCELLED" and "restarted" in j.task(stale)["error"]
    assert j.task(young)["status"] == "SUCCESS" and j.task(young)["result"] == "Fresh one answered."
    assert not script.queue
