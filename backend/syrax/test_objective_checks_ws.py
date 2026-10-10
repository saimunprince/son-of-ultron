"""A human can set a machine check on an objective over the WebSocket."""

from syrax.test_bridge import ORIGIN, TestClient, boot, recv_until, script, server  # noqa: F401


def test_objective_add_accepts_a_release_check_and_rejects_a_bad_one(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "objective_add", "goal": "Probe the GPU and release it", "priority": 1, "check": {"kind": "change_released"}})
        created, _ = recv_until(ws, "objective")
        assert created["event"] == "created" and created["source"] == "human"
        ws.send_json({"type": "objective_add", "goal": "bad", "priority": 1, "check": {"kind": "file_present"}})
        notice, _ = recv_until(ws, "notice")
        assert "needs 'path'" in notice["text"]
        ws.send_json({"type": "objectives", "limit": 5})
        rows, _ = recv_until(ws, "objectives")
        mine = [o for o in rows["objectives"] if o["id"] == created["objective_id"]][0]
        assert mine["check_spec"] == {"kind": "change_released"}
