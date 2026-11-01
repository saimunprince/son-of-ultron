"""Audit 2026-11-01 (integrations I-04, I-16): the last state a reconnecting client got was the snapshot taken before
the hello, the briefing and the replay, so a task that ended meanwhile left the UI busy; and the phone page's stop
button gave no word when the stop did not go through. Boot ends with the state as it is now, and the phone page says
whether the stop was sent."""

from syrax import phone
from syrax.test_bridge import ORIGIN, TestClient, boot, script, server  # noqa: F401


def test_boot_ends_with_the_live_state_not_the_snapshot(script, monkeypatch):
    from syrax import core as core_mod
    from syrax.test_bridge import recv_until

    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    real = core.snapshot

    def stale():  # the snapshot says a task runs; it ended before boot's last message
        snap = real()
        return {**snap, "running": {"task_id": "gone", "goal": "old", "stage": None, "step": 1, "status": "IN_PROGRESS",
                                    "phase": None, "kind": "conversation"}, "state": {"state": "acting"}}

    monkeypatch.setattr(core, "snapshot", stale)
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        recv_until(ws, "hello")
        _, seen = recv_until(ws, "task_events")
        last, _ = recv_until(ws, "state")
    assert last["state"] == "idle"  # the live state, not the snapshot's "acting"


def test_the_phone_page_reports_a_stop_that_did_not_go_through():
    assert "STOP NOT SENT" in phone.PAGE and "Stop sent." in phone.PAGE and "r.ok" in phone.PAGE
