"""EVOLUTION_PLAN wave 1 (direction 268 recovery validation): backups were verified file by file, but nothing ever
opened one as a journal with the key it carries and checked its chain, which is how the missing chain key went unseen
until 2026-10-29. backup.rehearse restores a snapshot aside and verifies its chain; the daily backup runs it."""

from pathlib import Path

from syrax import backup
from syrax.test_backup_chain_key import _journal


def test_a_good_snapshot_rehearses_clean_and_is_on_record(tmp_path):
    cfg, j = _journal(tmp_path)
    d = Path(backup.snapshot(j)["dir"])
    r = backup.rehearse(d, j)
    assert r["ok"] and r["chain"]["ok"] and r["chain"]["checked"] > 0
    last = [e for e in j.recent_events(20) if e["type"] == "backup.rehearsed"][-1]["payload"]
    assert last["ok"] is True and last["dir"] == str(d)


def test_a_snapshot_without_its_key_fails_the_rehearsal(tmp_path):
    cfg, j = _journal(tmp_path)
    d = Path(backup.snapshot(j)["dir"])
    (d / "journal.db.key").write_bytes(b"x" * 32)  # a different key: what a restore without the real one would get
    import json
    m = json.loads((d / "manifest.json").read_text())
    m["files"]["journal.db.key"] = {"bytes": 32, "sha256": backup._sha256(d / "journal.db.key")}
    (d / "manifest.json").write_text(json.dumps(m))
    r = backup.rehearse(d)
    assert not r["ok"] and any("chain does not verify" in p for p in r["problems"])
