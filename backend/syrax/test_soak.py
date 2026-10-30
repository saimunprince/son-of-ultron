"""EVOLUTION_PLAN wave 4 (directions 262 stress testing, 264 long-duration evaluation, 268 recovery validation): every
test ran one or two tasks, so slow leaks (worker processes left alive by a stop, memory that grows per task, tasks left
half-finished) could only show up after days of live use. This soak runs many tasks back to back through the real
socket and the real python_execute workers, stopping every third one mid-run and pressing the emergency stop once, and
then checks what must hold after any amount of use: no worker left alive, every task finished, the journal's chain
intact, and memory growth bounded."""

import os
import resource

import psutil

from syrax import estop
from syrax.journal import TERMINAL, get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, recv_until, reply, script, server  # noqa: F401

ROUNDS = 12


def workers():
    """Live descendants of this test process that are python_execute / skill workers (spawned interpreters)."""
    out = []
    for p in psutil.Process(os.getpid()).children(recursive=True):
        try:
            # spawned workers run multiprocessing.spawn's spawn_main; the resource_tracker lives as long as this
            # process by design and is no task's worker
            if p.status() != psutil.STATUS_ZOMBIE and "spawn_main" in " ".join(p.cmdline()):
                out.append(p.pid)
        except psutil.Error:
            continue
    return out


def test_many_tasks_with_stops_leave_nothing_behind(script):
    j = get_journal()
    before_tasks = len(j.tasks(limit=500))
    rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        for i in range(ROUNDS):
            if i % 3 == 2:  # a task stopped while its worker sleeps
                script.queue = [call("python_execute", {"code": "import time\ntime.sleep(30)"}, cid=f"s{i}"), reply("never")]
                ws.send_json({"type": "task", "text": f"slow job {i}"})
                recv_until(ws, "tool_start")
                ws.send_json({"type": "stop"})
                recv_until(ws, "notice")
                drain_until_idle(ws)
            else:
                script.queue = [call("python_execute", {"code": f"print({i} * 2)"}, cid=f"c{i}"), reply(f"{i * 2}.")]
                ws.send_json({"type": "task", "text": f"double {i}"})
                drain_until_idle(ws)
        estop.set_stop(j, "soak", "operator")  # own work refused while on; a human task still runs
        try:
            script.queue = [reply("still here.")]
            ws.send_json({"type": "task", "text": "are you there"})
            drain_until_idle(ws)
        finally:
            estop.clear_stop(j, "soak over", "operator")
    tasks = j.tasks(limit=500)[: len(j.tasks(limit=500)) - before_tasks]
    assert len(tasks) == ROUNDS + 1
    assert all(t["status"] in TERMINAL for t in tasks), [(t["goal"], t["status"]) for t in tasks]
    assert sum(t["status"] == "CANCELLED" for t in tasks) == ROUNDS // 3
    left = workers()
    assert left == [], [" ".join(psutil.Process(p).cmdline())[-160:] for p in left]  # no worker outlived its task
    assert j.verify_chain(5000)["ok"]
    grew_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - rss0) / 1024
    assert grew_mb < 300, f"peak memory grew {grew_mb:.0f} MB over {ROUNDS} tasks"


def _sleep():
    import time

    time.sleep(30)


def test_the_check_sees_a_live_worker():
    import multiprocessing

    p = multiprocessing.get_context("spawn").Process(target=_sleep)
    p.start()
    try:
        import time

        for _ in range(50):
            if p.pid in workers():
                break
            time.sleep(0.1)
        assert p.pid in workers()
    finally:
        p.kill()
        p.join(5)
