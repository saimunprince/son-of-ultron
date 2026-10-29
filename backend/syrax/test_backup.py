"""Milestone 3, backups with a tested restore: the journal (the whole evidence), brains.json (the API
keys), memory.json and config.toml are copied once a day into a verified, stamped folder, and a human
puts one back. A copy nobody ever opened is a hope, so every check here opens the copy.

No server, no brain, no network. Journals live in tmp_path, snapshots beside them."""

import asyncio
import importlib.util
import inspect
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from syrax import autonomy as auto
from syrax import backup
from syrax.autonomy import Autonomy
from syrax.devloop import JUDGES
from syrax.journal import Journal
from syrax.test_resources import IdleCore

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


def filled(tmp_path, n_tasks=3, objective=True) -> Journal:
    """A journal with tasks, events and (unless the test needs an idle cycle) an open objective, and the
    three config files beside it."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    j = Journal(cfg / "journal.db")
    for i in range(n_tasks):
        t = j.start_task_sync(f"task {i}")
        j.record_sync("think", {"step": 1, "content": f"thinking {i}"}, task_id=t)
        j.record_sync("final", {"content": f"done {i}"}, task_id=t)
    if objective:
        j.add_objective_sync("learn x", reason="why", priority=2, key="k1")
    (cfg / "brains.json").write_text(json.dumps({"keys": {"groq": "gsk_live_secret"}}), encoding="utf-8")
    (cfg / "memory.json").write_text(json.dumps({"facts": [{"text": "Prince builds products"}]}), encoding="utf-8")
    (cfg / "config.toml").write_text('[llm]\nmodel = "x"\n[daytona]\n', encoding="utf-8")
    return j


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)


# ——— snapshot and verify ———


def test_snapshot_copies_a_consistent_journal_and_the_manifest_tells_the_truth(tmp_path):
    j = filled(tmp_path)
    events_before = j.count("events")
    m = backup.snapshot(j)
    d = Path(m["dir"])
    assert d.parent == tmp_path / "config" / "backups" and backup.STAMP_RE.match(d.name)
    # exactly the five files (the chain key among them) and the manifest: the copy is self-contained, no -wal/-shm travel with it
    assert sorted(p.name for p in d.iterdir()) == ["brains.json", "config.toml", "journal.db", "journal.db.key", "manifest.json", "memory.json"]
    on_disk = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk["journal"] == m["journal"] == {"tasks": 3, "events": events_before, "objectives": 1, "integrity": "ok"}
    assert set(on_disk["files"]) == {"brains.json", "config.toml", "journal.db", "journal.db.key", "memory.json"}
    assert all(len(f["sha256"]) == 64 and f["bytes"] > 0 for f in on_disk["files"].values())
    assert on_disk["bytes"] == sum(f["bytes"] for f in on_disk["files"].values()) == m["bytes"]
    assert on_disk["secrets"] is True and "API keys" in on_disk["note"]  # the folder holds brains.json: it says so
    assert on_disk["git_head"] is None or len(on_disk["git_head"]) == 40
    assert (d / "brains.json").read_text(encoding="utf-8") == (tmp_path / "config" / "brains.json").read_text(encoding="utf-8")
    # the copy opens on its own and holds the same rows, as a plain rollback-journal database
    con = ro(d / "journal.db")
    assert [r[0] for r in con.execute("SELECT goal FROM tasks ORDER BY created")] == ["task 0", "task 1", "task 2"]
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    con.close()
    v = backup.verify(d)
    assert v["ok"] and v["problems"] == [] and v["journal"]["events"] == events_before
    # journaled: the event names the folder, the meta key makes it not due again for a day
    assert m["journaled"] is True
    last = j.recent_events()[-1]
    assert last["type"] == "backup.completed" and last["payload"]["dir"] == str(d) and last["payload"]["tasks"] == 3
    assert last["payload"]["integrity"] == "ok" and "brains.json" in last["payload"]["files"]
    assert j.count("events") == events_before + 1
    assert j.get_meta("last_backup") is not None and not backup.due(j)
    assert backup.due(j, now=time.time() + backup.EVERY_S)
    j.close()


def test_a_flipped_byte_a_missing_file_and_a_wrong_count_are_caught(tmp_path):
    j = filled(tmp_path)
    d = Path(backup.snapshot(j)["dir"])
    db = d / "journal.db"
    raw = bytearray(db.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    db.write_bytes(raw)
    v = backup.verify(d)
    assert not v["ok"] and any("journal.db: sha256" in p for p in v["problems"])
    raw[0] ^= 0xFF  # the header too: SQLite no longer recognises the file
    db.write_bytes(raw)
    v = backup.verify(d)
    assert any("integrity_check" in p for p in v["problems"])
    # a snapshot that does not verify is never restored
    r = backup.restore(d, config_dir=tmp_path / "config")
    assert not r["ok"] and r["problems"][0] == "the snapshot does not verify; nothing was touched"
    assert not (tmp_path / "config" / "backups").glob("_replaced-*") or not list((tmp_path / "config" / "backups").glob("_replaced-*"))
    # a missing file, a manifest that promises other counts, no manifest at all
    d2 = Path(backup.snapshot(j)["dir"])
    assert d2 != d
    (d2 / "brains.json").unlink()
    mf = json.loads((d2 / "manifest.json").read_text(encoding="utf-8"))
    mf["journal"]["tasks"] = 99
    (d2 / "manifest.json").write_text(json.dumps(mf), encoding="utf-8")
    v = backup.verify(d2)
    assert "brains.json: missing" in v["problems"] and any("3 tasks, the manifest says 99" in p for p in v["problems"])
    assert backup.verify(tmp_path)["ok"] is False
    j.close()


def test_a_copy_that_fails_is_journaled_and_leaves_no_half_written_folder(tmp_path, monkeypatch):
    j = filled(tmp_path)

    def boom(self, path):
        raise OSError("disk full")

    monkeypatch.setattr(Journal, "backup_to", boom)
    try:
        backup.snapshot(j)
        assert False, "snapshot must raise"
    except OSError as e:
        assert "disk full" in str(e)
    last = j.recent_events()[-1]
    assert last["type"] == "backup.failed" and "disk full" in last["payload"]["error"]
    assert j.get_meta("last_backup") is None  # still due: a failure is not a backup
    root = tmp_path / "config" / "backups"
    assert not root.exists() or list(root.iterdir()) == []
    j.close()


# ——— prune and due ———


def test_prune_keeps_the_newest_seven_and_touches_nothing_else(tmp_path):
    root = tmp_path / "backups"
    stamps = [f"202601{day:02d}-120000" for day in range(1, 10)]
    for s in stamps:
        (root / s).mkdir(parents=True)
        (root / s / "manifest.json").write_text("{}")
    (root / "20251201-000000").mkdir()  # stamped but no manifest: not a snapshot
    (root / "_replaced-20260110-090000").mkdir()
    (root / "_replaced-20260110-090000" / "journal.db").write_text("the journal a restore replaced")
    (root / "notes").mkdir()
    (root / "notes" / "manifest.json").write_text("{}")
    (root / "README.txt").write_text("mine")
    gone = backup.prune(root)
    assert gone == [str(root / s) for s in stamps[:2]]
    assert [p.name for p in backup.snapshots(root)] == stamps[2:]
    for name in ("20251201-000000", "_replaced-20260110-090000", "notes", "README.txt"):
        assert (root / name).exists(), name
    assert backup.prune(root) == []  # a second run removes nothing
    assert len(backup.prune(root, keep=0)) == 6 and len(backup.snapshots(root)) == 1  # never below one
    assert backup.prune(tmp_path / "nowhere") == []


def test_due_follows_the_last_backup_meta_key(tmp_path):
    j = Journal(tmp_path / "j.db")
    now = time.time()
    assert backup.due(j, now=now)
    j.set_meta("last_backup", str(now))
    assert not backup.due(j, now=now + 10) and not backup.due(j, now=now + backup.EVERY_S - 1)
    assert backup.due(j, now=now + backup.EVERY_S) and backup.due(j, every_s=5, now=now + 5)
    j.set_meta("last_backup", "garbage")
    assert backup.due(j, now=now)
    j.close()


# ——— restore ———


def test_restore_reproduces_the_rows_and_refuses_while_syrax_runs(tmp_path, monkeypatch):
    j = filled(tmp_path)
    cfg = tmp_path / "config"
    m = backup.snapshot(j)
    d = Path(m["dir"])
    # life goes on after the snapshot: more rows, a rotated key
    t = j.start_task_sync("after the snapshot")
    j.record_sync("think", {"step": 1, "content": "x"}, task_id=t)
    (cfg / "brains.json").write_text('{"keys": {"groq": "rotated"}}', encoding="utf-8")
    j.close()
    (cfg / "journal.db-wal").write_bytes(b"a stale wal must not be applied to the restored journal")
    monkeypatch.setattr(backup, "running", lambda config_dir=None: "pid 4242 is alive")
    r = backup.restore(d, config_dir=cfg)
    assert not r["ok"] and r["problems"] == ["SYRAX is running (pid 4242 is alive); nothing was touched"]
    assert "rotated" in (cfg / "brains.json").read_text(encoding="utf-8") and not list((cfg / "backups").glob("_replaced-*"))
    monkeypatch.setattr(backup, "running", lambda config_dir=None: None)
    r = backup.restore(d, config_dir=cfg)
    assert r["ok"] and sorted(r["restored"]) == ["brains.json", "config.toml", "journal.db", "journal.db.key", "memory.json"]
    aside = Path(r["replaced_to"])
    assert aside.parent == cfg / "backups" and aside.name.startswith("_replaced-")
    assert sorted(r["replaced"]) == ["brains.json", "config.toml", "journal.db", "journal.db-wal", "journal.db.key", "memory.json"]
    assert "rotated" in (aside / "brains.json").read_text(encoding="utf-8") and (aside / "journal.db-wal").exists()
    assert not (cfg / "journal.db-wal").exists()
    assert (cfg / "brains.json").read_text(encoding="utf-8") == (d / "brains.json").read_text(encoding="utf-8")
    back = Journal(cfg / "journal.db", recover=False)  # the snapshot's rows, nothing after it
    assert back.count("tasks") == m["journal"]["tasks"] == 3 and back.count("events") == m["journal"]["events"]
    assert back.count("objectives") == 1 and "after the snapshot" not in [x["goal"] for x in back.tasks()]
    assert back.pragma("journal_mode") == "wal"  # the journal takes its WAL mode back on open
    back.close()
    old = ro(aside / "journal.db")
    assert old.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 4  # the replaced journal is kept whole
    old.close()
    assert backup.verify(d)["ok"]  # the snapshot itself is untouched by its restore


def test_running_sees_the_pid_file_the_port_and_a_live_owner_of_the_journal(tmp_path, monkeypatch):
    pid = tmp_path / "syrax.pid"
    monkeypatch.setattr(backup, "PID_FILE", pid)
    monkeypatch.setattr(backup, "port_in_use", lambda port: False)
    assert backup.running(tmp_path) is None
    pid.write_text("4242")
    why = backup.running(tmp_path)
    assert "4242" in why and "--stop" in why
    pid.unlink()
    monkeypatch.setattr(backup, "port_in_use", lambda port: port == backup.BACKEND_PORT)
    assert f"port {backup.BACKEND_PORT}" in backup.running(tmp_path)
    monkeypatch.setattr(backup, "port_in_use", lambda port: False)
    # another live process has the journal open: the owner lock says so
    code = ("import sys, time; from syrax.journal import Journal; j = Journal(sys.argv[1]); print('open', flush=True); "
            "time.sleep(60)")
    child = subprocess.Popen([sys.executable, "-c", code, str(tmp_path / "journal.db")], cwd=str(BACKEND),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "open"
        assert "owns" in (backup.running(tmp_path) or "")
    finally:
        child.kill()
        child.wait(timeout=10)
    for _ in range(50):  # Windows lets go of a dead process's lock a moment after wait() returns
        if backup.running(tmp_path) is None:
            break
        time.sleep(0.1)
    assert backup.running(tmp_path) is None


# ——— the idle cycle ———


def test_the_idle_cycle_backs_up_once_a_day_before_maintenance_and_survives_a_failure(tmp_path, monkeypatch):
    j = filled(tmp_path, objective=False)  # nothing to work on: the cycle idles
    root = tmp_path / "config" / "backups"
    a = Autonomy(IdleCore(j), j)
    a.set_enabled(True)
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "IDLE" and "backup: " in rep.reason and "maintenance: " in rep.reason, rep.reason
    assert rep.reason.index("backup") < rep.reason.index("maintenance")
    snaps = backup.snapshots(root)
    assert len(snaps) == 1 and backup.verify(snaps[0])["ok"] and snaps[0].name in rep.reason
    kinds = [e["type"] for e in j.recent_events()]
    assert kinds.index("backup.completed") < kinds.index("maintenance.completed")
    assert j.get_meta("last_backup") is not None
    rep2 = asyncio.run(a.run_once())
    assert rep2.outcome == "IDLE" and rep2.reason == "no open objective" and len(backup.snapshots(root)) == 1  # not due again

    def boom(self, path):
        raise OSError("disk full")

    monkeypatch.setattr(backup, "due", lambda journal, every_s=backup.EVERY_S, now=None: True)
    monkeypatch.setattr(Journal, "backup_to", boom)
    rep3 = asyncio.run(a.run_once())
    assert rep3.outcome == "IDLE" and rep3.reason == "no open objective"  # the cycle completes; nothing pretends
    failed = [e for e in j.recent_events() if e["type"] == "backup.failed"]
    assert failed and "disk full" in failed[-1]["payload"]["error"]
    assert [p.name for p in root.iterdir()] == [snaps[0].name]  # no half-written folder
    j.close()


# ——— guarded, not a tool, reachable from the launcher ———


def test_backup_is_a_judge_and_no_agent_tool():
    assert "backend/syrax/backup.py" in JUDGES
    from app.tool.base import BaseTool

    assert not any(inspect.isclass(o) and issubclass(o, BaseTool) for o in vars(backup).values())
    for mod in ("agent.py", "core.py", "tools.py"):
        p = Path(backup.__file__).parent / mod
        if p.exists():
            src = p.read_text(encoding="utf-8")
            assert "syrax.backup" not in src and "import backup" not in src, mod
    assert "No agent tool exposes snapshot or restore and none may be added" in " ".join(backup.__doc__.split())


def test_the_command_line_snapshots_verifies_and_refuses_a_restore_while_running(tmp_path, monkeypatch, capsys):
    j = filled(tmp_path)
    cfg = tmp_path / "config"
    j.close()
    monkeypatch.setenv("SYRAX_JOURNAL_FILE", str(cfg / "journal.db"))
    assert backup.main(["--snapshot"]) == 0
    out = capsys.readouterr().out
    assert "verified: ok" in out and "API keys" in out and "3 tasks" in out
    d = backup.snapshots(cfg / "backups")[0]
    assert backup.main(["--verify", str(d)]) == 0
    monkeypatch.setattr(backup, "running", lambda config_dir=None: "pid 1 is alive")
    assert backup.main(["--restore", str(d)]) == 1
    assert "refused" in capsys.readouterr().out and (cfg / "journal.db").exists()
    (d / "memory.json").write_text("{}", encoding="utf-8")  # tampered
    assert backup.main(["--verify", str(d)]) == 1
    assert "memory.json" in capsys.readouterr().out
    monkeypatch.setenv("SYRAX_JOURNAL_FILE", str(tmp_path / "nowhere.db"))
    assert backup.main(["--snapshot"]) == 1


def test_the_launcher_routes_backup_and_restore_to_the_backend_venv(monkeypatch):
    spec = importlib.util.spec_from_file_location("syrax_launcher_backup", ROOT / "syrax.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = []

    class Done:
        returncode = 0

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return Done()

    monkeypatch.setattr(mod, "setup", lambda verbose=False: None)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.main(["--backup"]) == 0
    assert mod.main(["--restore", "backend/config/backups/20260101-000000"]) == 0
    assert calls[0][0] == [str(mod.venv_python()), "-m", "syrax.backup", "--snapshot"] and calls[0][1]["cwd"] == str(mod.BACKEND)
    assert calls[1][0][:4] == [str(mod.venv_python()), "-m", "syrax.backup", "--restore"]
    assert os.path.isabs(calls[1][0][4]) and calls[1][0][4].endswith("20260101-000000") and calls[1][1]["cwd"] == str(mod.BACKEND)
