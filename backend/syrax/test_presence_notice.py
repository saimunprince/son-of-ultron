"""Audit 2026-11-01 (integrations I-05): "show me", "minimize" or "hide" typed in the web UI changed the desktop HUD's
visibility and said nothing; the web UI does not show presence, so the command looked ignored. A notice says what
happened."""

from syrax.test_bridge import ORIGIN, TestClient, boot, recv_until, script, server  # noqa: F401


def test_a_visibility_command_from_the_web_ui_is_answered(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "hide"})
        notice, _ = recv_until(ws, "notice")
    assert "HUD visibility" in notice["text"] and "not a task" in notice["text"]
    assert script.seen == []  # no task, no brain
