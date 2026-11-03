"""2026-11-03: hand gestures act in the HUD (thumbs up, swipes, the E-STOP ...). Each one the HUD acted on is
journaled as gesture.used, so SYRAX can tell what the human did with their hands; no task is started."""

import json

from syrax.test_bridge import ORIGIN, TestClient, boot, get_journal, recv_until, script, server  # noqa: F401


def test_a_gesture_is_journaled_without_a_task(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        before = len(get_journal().tasks(limit=500))
        ws.send_json({"type": "gesture", "gesture": "thumbs_up", "detail": "answered yes"})
        ws.send_json({"type": "gesture", "gesture": "<script>"})  # only letters and _ are kept
        ws.send_json({"type": "ping"})
        recv_until(ws, "pong")  # messages are handled in order: both gestures are in
    j = get_journal()
    got = [json.loads(r[0]) for r in j._db.execute("SELECT payload FROM events WHERE type='gesture.used' ORDER BY id")]
    assert {"gesture": "thumbs_up", "detail": "answered yes"} in got and {"gesture": "script", "detail": ""} in got
    assert len(j.tasks(limit=500)) == before
