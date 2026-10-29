"""2026-10-29 (AUDIT_2026-10-28 open item: no integrity chain on the journal): every kept event now carries an HMAC
over its own fields and the previous chained event's HMAC. The key lives beside the journal in backend/config, which
SYRAX's own code may neither read nor write, so an edited, inserted or deleted event is found by verify_chain, while
maintenance's pruning of think/brain/presentation events (never chained) is not mistaken for tampering."""

import os
import sqlite3
import time

from syrax import guard
from syrax import permissions as P
from syrax.journal import UNCHAINED, Journal


def fill(j, n=6):
    t = j.start_task_sync("chain test")
    for i in range(n):
        j.record_sync("think" if i % 2 else "tool.started", {"i": i}, task_id=t)
    return t


def raw(j):
    c = sqlite3.connect(str(j.path))
    c.isolation_level = None
    return c


def test_a_clean_journal_verifies_and_its_key_is_private(tmp_path):
    j = Journal(tmp_path / "j.db")
    fill(j)
    v = j.verify_chain()
    assert v["ok"] and v["checked"] >= 3
    key = tmp_path / "j.db.key"
    assert key.exists() and (os.name != "posix" or (os.stat(key).st_mode & 0o777) == 0o600)  # no mode bits on Windows
    assert "think" in UNCHAINED


def test_an_edited_payload_is_found(tmp_path):
    j = Journal(tmp_path / "j.db")
    fill(j)
    victim = j._db.execute("SELECT id FROM events WHERE chain IS NOT NULL ORDER BY id LIMIT 1 OFFSET 1").fetchone()[0]
    raw(j).execute("UPDATE events SET payload='{\"i\": 99}' WHERE id=?", (victim,))
    v = j.verify_chain()
    assert not v["ok"] and v["first_bad"] == victim


def test_a_deleted_chained_event_is_found_but_pruning_is_not(tmp_path):
    j = Journal(tmp_path / "j.db")
    fill(j, 8)
    c = raw(j)
    c.execute("DELETE FROM events WHERE type='think'")  # what maintenance prunes: never chained
    assert j.verify_chain()["ok"]
    victim = j._db.execute("SELECT id FROM events WHERE chain IS NOT NULL ORDER BY id LIMIT 1 OFFSET 1").fetchone()[0]
    c.execute("DELETE FROM events WHERE id=?", (victim,))
    v = j.verify_chain()
    assert not v["ok"] and v["first_bad"] > victim


def test_a_forged_event_without_the_key_is_found(tmp_path):
    j = Journal(tmp_path / "j.db")
    fill(j)
    raw(j).execute("INSERT INTO events(ts, task_id, type, payload, seq, chain) VALUES (?,?,?,?,?,?)",
                   (time.time(), None, "estop.cleared", '{"by": "me"}', 0, "0" * 64))
    v = j.verify_chain()
    assert not v["ok"] and "changed, added or removed" in v["reason"]
    raw(j).execute("INSERT INTO events(ts, task_id, type, payload, seq) VALUES (?,?,?,?,?)",
                   (time.time(), None, "estop.cleared", '{"by": "me"}', 0))
    j2 = Journal(tmp_path / "k.db")
    fill(j2)
    raw(j2).execute("INSERT INTO events(ts, task_id, type, payload, seq) VALUES (?,?,?,?,?)",
                    (time.time(), None, "estop.cleared", '{"by": "me"}', 0))
    v2 = j2.verify_chain()
    assert not v2["ok"] and "no chain value" in v2["reason"]  # an unchained evidence event is a gap


def test_the_key_is_as_protected_as_the_journal():
    assert any(p.endswith(".key") for p in guard.protected_paths())
    assert "backend/config/journal.db.key" in P.PROTECTED_DATA


def test_every_boot_checks_the_chain_on_record():
    from fastapi.testclient import TestClient

    from syrax import server
    from syrax.journal import get_journal
    from syrax.test_bridge import ORIGIN, boot

    with TestClient(server.app) as client:  # as a context manager: the server's startup (lifespan) runs
        with client.websocket_connect("/ws", headers=ORIGIN) as ws:
            boot(ws)
    checks = [e["payload"] for e in get_journal().recent_events(500) if e["type"] == "integrity.checked"]
    assert checks and checks[-1]["ok"] is True and "checked" in checks[-1]
