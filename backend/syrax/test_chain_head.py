"""Audit 2026-11-01 (lifecycle LIFE-3, confirmed): verify_chain passed when the newest chained events were deleted
and when every chain value was wiped. A signed chain head, written in the same transaction as each chained event,
catches both; a journal from before the head existed is still checked as before."""

from syrax.journal import CHAIN_HEAD, Journal


def chained(tmp_path, n=4):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("x")
    for i in range(n):
        j.record_sync("tool.started", {"id": f"c{i}", "name": "desktop", "args": {}}, task_id=t)
    return j


def test_a_sound_journal_verifies(tmp_path):
    assert chained(tmp_path).verify_chain()["ok"] is True


def test_deleting_the_tail_is_caught(tmp_path):
    j = chained(tmp_path)
    last = j._db.execute("SELECT MAX(id) FROM events WHERE chain IS NOT NULL").fetchone()[0]
    j._db.execute("DELETE FROM events WHERE id>=?", (last - 1,))
    v = j.verify_chain()
    assert v["ok"] is False and "removed" in v["reason"]


def test_wiping_the_chain_is_caught(tmp_path):
    j = chained(tmp_path)
    j._db.execute("UPDATE events SET chain=NULL")
    v = j.verify_chain()
    assert v["ok"] is False and ("wiped" in v["reason"] or "no chain value" in v["reason"])


def test_a_forged_head_is_caught_and_a_journal_without_one_still_verifies(tmp_path):
    j = chained(tmp_path)
    j._db.execute("UPDATE meta SET value=? WHERE key=?", ('{"id": 1, "chain": "x", "sig": "y"}', CHAIN_HEAD))
    assert "signature" in j.verify_chain()["reason"]
    j._db.execute("DELETE FROM meta WHERE key=?", (CHAIN_HEAD,))
    assert j.verify_chain()["ok"] is True  # legacy: no head yet
