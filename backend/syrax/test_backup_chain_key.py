"""Audit 2026-10-28, open item: the journal's HMAC chain key (journal.db.key) was not in the backups. A journal put
back on a new PC (as after the 2026-09-30 move) came without the key that signed it: a fresh key was made on first
use and every kept chain value failed verify_chain. The key now travels with the journal, private like brains.json,
and comes back with it at mode 600."""

import os
import stat
from pathlib import Path

from syrax import backup
from syrax.journal import Journal


def _journal(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    j = Journal(cfg / "journal.db")
    t = j.start_task_sync("signed work")
    j.record_sync("think", {"step": 1, "content": "x"}, task_id=t)
    j.record_sync("final", {"content": "done"}, task_id=t)
    assert j.verify_chain()["ok"] and (cfg / "journal.db.key").is_file()
    return cfg, j


def test_the_snapshot_holds_the_key_and_says_it_is_secret(tmp_path):
    cfg, j = _journal(tmp_path)
    m = backup.snapshot(j)
    d = Path(m["dir"])
    assert (d / "journal.db.key").read_bytes() == (cfg / "journal.db.key").read_bytes()
    assert "journal.db.key" in m["files"] and m["secrets"] is True and "journal.db.key" in m["note"]
    assert backup.verify(d)["ok"]


def test_a_journal_restored_onto_a_pc_without_its_key_still_verifies(tmp_path, monkeypatch):
    cfg, j = _journal(tmp_path)
    d = Path(backup.snapshot(j)["dir"])
    j.close()
    (cfg / "journal.db.key").unlink()  # the new PC: the journal comes back, the old key is gone
    monkeypatch.setattr(backup, "running", lambda config_dir=None: None)
    r = backup.restore(d, config_dir=cfg)
    assert r["ok"] and "journal.db.key" in r["restored"]
    if os.name == "posix":  # Windows has no owner-only mode bits
        assert stat.S_IMODE(os.stat(cfg / "journal.db.key").st_mode) == 0o600
    back = Journal(cfg / "journal.db", recover=False)
    v = back.verify_chain()
    assert v["ok"] and v["checked"] > 0, v
