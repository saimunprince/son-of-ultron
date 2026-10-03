"""Live 2026-10-03: an autonomous release was "aborted by human" and nothing
said who sent the stop. The stop is journaled with where it came from."""

from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, recv_until, script, server  # noqa: F401


def test_a_stop_is_journaled_with_its_source(script):
    script.queue = [call("slow", {}, cid="call_slow")]
    with TestClient(server.app).websocket_connect("/ws", headers={**ORIGIN, "user-agent": "orb-ui"}) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "wait"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "stop", "reason": "ESC pressed"})
        drain_until_idle(ws)
    j = get_journal()
    task = j.tasks()[0]
    ev = [e for e in j.events(task["task_id"]) if e["type"] == "task.stop_requested"]
    assert task["status"] == "CANCELLED" and len(ev) == 1
    assert ev[0]["payload"]["origin"] == ORIGIN["origin"] and ev[0]["payload"]["client"] == "orb-ui"
    assert ev[0]["payload"]["reason"] == "ESC pressed"
