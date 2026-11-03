"""2026-11-03: the HUD's gauges (JARVIS theme) ask for `vitals` and get the live resource snapshot: CPU load,
memory, disk and temperatures. Read-only, no task."""

from syrax.test_bridge import ORIGIN, TestClient, boot, get_journal, recv_until, script, server  # noqa: F401


def test_vitals_are_sent_on_request_without_a_task(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        before = len(get_journal().tasks(limit=500))
        ws.send_json({"type": "vitals"})
        v, _ = recv_until(ws, "vitals")
    assert {"cpu", "memory_mb", "disk", "temperatures"} <= set(v)
    assert v["cpu"]["cores"] >= 1
    assert len(get_journal().tasks(limit=500)) == before
