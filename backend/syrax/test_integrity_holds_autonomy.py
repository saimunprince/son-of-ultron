"""Audit 2026-11-01 (lifecycle LIFE-4): a broken journal chain at boot only reached the log, and SYRAX's own work
started as usual. Now the emergency stop is set (the human clears it) and an integrity alert is journaled."""

from fastapi.testclient import TestClient

from syrax import estop, server
from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, boot


def test_a_broken_chain_at_boot_stops_own_work_until_the_human_looks():
    j = get_journal()
    t = j.start_task_sync("something to chain")
    j.record_sync("final", {"text": "done"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS", "result": "done"}, task_id=t)
    first = j._db.execute("SELECT id FROM events WHERE chain IS NOT NULL ORDER BY id LIMIT 1 OFFSET 1").fetchone()[0]
    j._db.execute("UPDATE events SET payload=? WHERE id=?", ('{"text": "changed"}', first))
    try:
        with TestClient(server.app) as client:
            with client.websocket_connect("/ws", headers=ORIGIN) as ws:
                boot(ws)
        j = get_journal()
        check = [e["payload"] for e in j.recent_events(500) if e["type"] == "integrity.checked"][0]
        assert check["ok"] is False
        assert estop.active(j)
        alerts = [e["payload"] for e in j.recent_events(500) if e["type"] == "alert.raised"]
        assert alerts and alerts[0]["kind"] == "integrity"
    finally:
        estop.clear_stop(get_journal(), "test over", "operator")


def test_a_sound_chain_sets_no_stop():
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws", headers=ORIGIN) as ws:
            boot(ws)
    j = get_journal()
    assert [e["payload"]["ok"] for e in j.recent_events(500) if e["type"] == "integrity.checked"][0] is True
    assert not estop.active(j)
