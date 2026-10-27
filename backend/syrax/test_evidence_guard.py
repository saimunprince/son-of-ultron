"""Audit 2026-10-27, protected audit evidence: SYRAX cannot rewrite its backups, a forged snapshot does not
restore, and its own work cannot land without the independent review.

(1) backend/config/backups/ held verified snapshots of the journal and the keys, but nothing protected the
    folder: a tool could rewrite a snapshot together with its manifest.json, and restore() verified the
    snapshot against that same manifest. Now every write under it is refused at the gate for every task
    kind (permissions.PROTECTED_DIRS), SYRAX's own work does not read it either, and the python_execute
    guard blocks writes there (guard.protected_paths).
(2) snapshot() journals the manifest's sha256 in backup.completed; restore() refuses a snapshot whose
    manifest differs from the journaled hash. A snapshot with no journaled hash restores with a warning.
(3) devloop skipped the review silently when no reviewer was wired; an autonomous or eval change with no
    reviewer is now held as REVIEW_UNAVAILABLE, and a {skipped} verdict counts only when the service was
    started with SYRAX_REVIEW=0.
"""

import asyncio
import json
import os
import sqlite3
from pathlib import Path

import pytest

from syrax import backup, guard
from syrax import permissions as P
from syrax.devloop import DevLoop
from syrax.journal import Journal
from syrax.test_devloop import PASS, git, repo

BACKUPS = P.REPO_ROOT / "backend" / "config" / "backups"
SNAP = BACKUPS / "20261027-101500"
PLAN = {"why": "objective evidence", "risk": "callers of mod", "tests": "test_mod.py"}


def editor(path, cmd="str_replace"):
    return P.classify("str_replace_editor", {"command": cmd, "path": str(path), "old_str": "a", "new_str": "b", "file_text": "x"})


# ——— (1) the gate ———

@pytest.mark.parametrize("kind", P.KINDS)
@pytest.mark.parametrize("target", [SNAP / "manifest.json", SNAP / "journal.db", SNAP / "brains.json", BACKUPS / "new.txt",
                                    str(SNAP / "manifest.json").replace("\\", "/").upper(),
                                    P.REPO_ROOT / ".syrax" / "worktrees" / "t1" / "backend" / "config" / "backups" / "s" / "manifest.json"])
def test_a_write_under_the_backups_is_refused_for_every_kind(kind, target):
    v = P.decide(editor(target, "create"), kind, f"please rewrite {target}")
    assert v.action == "refuse" and v.authorized_by is None, v
    assert "backups" in v.reason and "only a human" in v.reason


@pytest.mark.parametrize("target", ["backend/config/backups/x/manifest.json", "backend\\config\\backups\\x\\journal.db",
                                    "./backend/config/backups/x", str(BACKUPS / "s" / ".." / "t" / "manifest.json")])
def test_every_spelling_of_a_backup_path_is_recognised(target):
    hits = P.dir_targets([target])
    assert hits and hits[0].startswith("backend/config/backups/"), hits


@pytest.mark.parametrize("kind", P.KINDS)
def test_python_code_and_a_patch_that_write_a_snapshot_are_refused(kind):
    code = f'open(r"{SNAP / "manifest.json"}", "w").write("{{}}")'
    v = P.decide(P.classify("python_execute", {"code": code}), kind, "fix the manifest")
    assert v.action == "refuse" and "backups" in v.reason, v
    diff = "--- a/backend/config/backups/s/manifest.json\n+++ b/backend/config/backups/s/manifest.json\n@@ -1 +1 @@\n-{}\n+{\"x\": 1}\n"
    v = P.decide(P.classify("apply_patch", {"diff": diff}), kind, "fix the manifest")
    assert v.action == "refuse" and "backups" in v.reason, v


def test_reading_the_backups_is_the_conversations_only():
    view = editor(SNAP / "manifest.json", "view")
    assert view.level == P.READ_ONLY
    assert P.decide(view, "conversation", "show me the last backup's manifest").action == "allow"
    for kind in ("autonomous", "eval"):
        v = P.decide(view, kind, "")
        assert v.action == "refuse" and "backups" in v.reason and "neither reads nor writes" in v.reason, v


@pytest.mark.parametrize("target", ["backend/config/backups.txt", "backend/config/backupsX/a", "backend/config/brains.json",
                                    str(P.REPO_ROOT / "backend" / "syrax" / "backup.py"), "C:/elsewhere/backend/config/backups/a", ""])
def test_other_paths_are_not_the_backups(target):
    assert P.dir_targets([target]) == []


def test_the_backups_folder_itself_is_protected():
    assert P.dir_targets([str(BACKUPS)]) == ["backend/config/backups"]
    assert P.dir_targets(["backend/config/backups/"]) == ["backend/config/backups"]


# ——— (1) the python_execute guard ———

def test_the_guard_lists_the_backups_folder_beside_the_journal(monkeypatch, tmp_path):
    monkeypatch.setenv("SYRAX_JOURNAL_FILE", str(tmp_path / "config" / "journal.db"))
    paths = guard.protected_paths()
    want = f"{(tmp_path / 'config' / 'backups').resolve()}{os.sep}"
    assert want in paths and not want.endswith("*")


def _child(code: str, paths, tmp_path) -> str:
    """Run code in a child Python with the guard installed through sitecustomize (as python_execute's children are)."""
    import subprocess
    import sys

    env = dict(os.environ)
    env[guard.ENV] = os.pathsep.join(paths)
    env["PYTHONPATH"] = guard.SITE_DIR + os.pathsep + str(Path(guard.__file__).resolve().parents[1])
    script = tmp_path / "child.py"
    script.write_text(code, encoding="utf-8")
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env, timeout=60)
    return out.stdout + out.stderr


def test_a_guarded_child_cannot_write_rename_or_delete_a_snapshot(tmp_path):
    cfg = tmp_path / "config"
    snap = cfg / "backups" / "20261027-101500"
    snap.mkdir(parents=True)
    (snap / "manifest.json").write_text("{}", encoding="utf-8")
    con = sqlite3.connect(snap / "journal.db")
    con.execute("CREATE TABLE t (x)")
    con.commit()
    con.close()
    (cfg / "elsewhere.txt").write_text("ok", encoding="utf-8")
    paths = [str(cfg / "journal.db"), f"{(cfg / 'backups').resolve()}{os.sep}", f"!{cfg / 'backups'}{os.sep}*"]
    code = f"""
import os, shutil, sqlite3
snap = r"{snap}"
def tried(what, fn):
    try:
        fn()
        print(what, "WROTE")
    except PermissionError as e:
        print(what, "BLOCKED")
tried("open", lambda: open(os.path.join(snap, "manifest.json"), "w").write("forged"))
tried("append", lambda: open(os.path.join(snap, "manifest.json"), "a").write("forged"))
tried("new", lambda: open(os.path.join(snap, "x.json"), "w").write("forged"))
tried("newstamp", lambda: open(os.path.join(os.path.dirname(snap), "20990101-000000-manifest.json"), "w").write("x"))
tried("remove", lambda: os.remove(os.path.join(snap, "manifest.json")))
tried("rename", lambda: os.rename(os.path.join(snap, "manifest.json"), os.path.join(snap, "m2.json")))
tried("replace_in", lambda: os.replace(r"{cfg / 'elsewhere.txt'}", os.path.join(snap, "manifest.json")))
tried("rename_dir", lambda: os.rename(os.path.dirname(snap), os.path.dirname(snap) + "-old"))
tried("rmtree", lambda: shutil.rmtree(snap))
c = sqlite3.connect(os.path.join(snap, "journal.db"))
try:
    c.execute("INSERT INTO t VALUES (1)"); c.commit(); print("sqlite WROTE")
except sqlite3.OperationalError as e:
    print("sqlite BLOCKED", e)
print("read", open(os.path.join(snap, "manifest.json")).read())
"""
    out = _child(code, paths, tmp_path)
    for what in ("open", "append", "new", "newstamp", "remove", "rename", "replace_in", "rename_dir", "rmtree"):
        assert f"{what} BLOCKED" in out, out
    assert "WROTE" not in out and "read {}" in out, out
    assert "sqlite BLOCKED" in out or "readonly" in out.lower(), out
    assert (snap / "manifest.json").read_text(encoding="utf-8") == "{}"


def test_an_ordinary_write_beside_the_backups_still_works(tmp_path):
    cfg = tmp_path / "config"
    (cfg / "backups").mkdir(parents=True)
    paths = [str(cfg / "journal.db"), f"{(cfg / 'backups').resolve()}{os.sep}"]
    out = _child(f'open(r"{cfg / "notes.txt"}", "w").write("x"); print("done")', paths, tmp_path)
    assert "done" in out and (cfg / "notes.txt").read_text() == "x", out


# ——— (2) the journaled manifest hash ———

def filled(tmp_path) -> Journal:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "brains.json").write_text('{"keys": {"groq": "k"}}', encoding="utf-8")
    j = Journal(cfg / "journal.db")
    t = j.start_task_sync("a task")
    j.record_sync("think", {"step": 1, "content": "x"}, task_id=t)
    return j


def test_the_snapshot_journals_its_manifests_hash(tmp_path):
    j = filled(tmp_path)
    m = backup.snapshot(j)
    d = Path(m["dir"])
    last = j.recent_events()[-1]
    assert last["type"] == "backup.completed"
    assert last["payload"]["manifest_sha256"] == backup._sha256(d / "manifest.json") == m["manifest_sha256"]
    j.close()
    assert backup.journaled_manifests(d, tmp_path / "config") == [m["manifest_sha256"]]


def _forge(d: Path) -> None:
    """Rewrite brains.json and the manifest to match it: the snapshot still verifies against itself."""
    (d / "brains.json").write_text('{"keys": {"groq": "forged"}}', encoding="utf-8")
    mf = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    mf["files"]["brains.json"] = {"bytes": (d / "brains.json").stat().st_size, "sha256": backup._sha256(d / "brains.json")}
    mf["bytes"] = sum(f["bytes"] for f in mf["files"].values())
    (d / "manifest.json").write_text(json.dumps(mf, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_a_snapshot_forged_with_its_manifest_verifies_but_does_not_restore(tmp_path, monkeypatch):
    j = filled(tmp_path)
    cfg = tmp_path / "config"
    d = Path(backup.snapshot(j)["dir"])
    j.close()
    _forge(d)
    assert backup.verify(d)["ok"]  # the folder alone cannot tell
    monkeypatch.setattr(backup, "running", lambda config_dir=None: None)
    r = backup.restore(d, config_dir=cfg)
    assert not r["ok"] and r["restored"] == []
    assert "not the one the journal recorded" in r["problems"][0] and "nothing was touched" in r["problems"][0]
    assert json.loads((cfg / "brains.json").read_text(encoding="utf-8"))["keys"]["groq"] == "k"
    assert not list((cfg / "backups").glob("_replaced-*"))


def test_an_untouched_journaled_snapshot_restores_without_a_warning(tmp_path, monkeypatch):
    j = filled(tmp_path)
    cfg = tmp_path / "config"
    d = Path(backup.snapshot(j)["dir"])
    j.close()
    monkeypatch.setattr(backup, "running", lambda config_dir=None: None)
    r = backup.restore(d, config_dir=cfg)
    assert r["ok"] and r["warnings"] == [] and "journal.db" in r["restored"]


def test_a_snapshot_with_no_journaled_hash_restores_with_a_warning(tmp_path, monkeypatch):
    j = filled(tmp_path)
    cfg = tmp_path / "config"
    d = Path(backup.snapshot(j)["dir"])
    # as before the rule: the event carries no manifest hash
    with j._txn() as cur:
        cur.execute("UPDATE events SET payload=json_remove(payload, '$.manifest_sha256') WHERE type='backup.completed'")
    j.close()
    assert backup.journaled_manifests(d, cfg) == []
    monkeypatch.setattr(backup, "running", lambda config_dir=None: None)
    r = backup.restore(d, config_dir=cfg)
    assert r["ok"] and len(r["warnings"]) == 1 and "no manifest hash was journaled" in r["warnings"][0]


def test_with_no_journal_to_read_the_snapshot_restores_with_a_warning(tmp_path, monkeypatch):
    j = filled(tmp_path)
    cfg = tmp_path / "config"
    d = Path(backup.snapshot(j)["dir"])
    j.close()
    for p in cfg.glob("journal.db*"):
        p.unlink()
    assert backup.journaled_manifests(d, cfg) is None
    monkeypatch.setattr(backup, "running", lambda config_dir=None: None)
    r = backup.restore(d, config_dir=cfg)
    assert r["ok"] and "no journal to read" in r["warnings"][0]


def test_reading_the_journal_for_the_hash_writes_nothing(tmp_path):
    j = filled(tmp_path)
    cfg = tmp_path / "config"
    d = Path(backup.snapshot(j)["dir"])
    j.close()
    before = (cfg / "journal.db").read_bytes()
    beside = sorted(p.name for p in cfg.glob("journal.db*"))
    assert backup.journaled_manifests(d, cfg)
    assert (cfg / "journal.db").read_bytes() == before
    assert sorted(p.name for p in cfg.glob("journal.db*")) == beside and "journal.db-shm" not in beside  # no -wal/-shm made


# ——— (3) the review cannot be bypassed ———

def loop(tmp_path, root, kind, reviewer=None, opt_out=None, monkeypatch=None):
    if monkeypatch is not None and opt_out is not None:
        monkeypatch.setenv("SYRAX_REVIEW", opt_out)
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("improve mod", kind=kind)
    j.record_sync("brain.answered", {"provider": "gemini"}, task_id=t)
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    dl.reviewer = reviewer
    return j, t, dl


@pytest.mark.parametrize("kind", ["autonomous", "eval"])
def test_own_work_with_no_reviewer_wired_is_held(tmp_path, kind, monkeypatch):
    root = repo(tmp_path)
    head0 = git(root, "rev-parse", "HEAD")
    j, t, dl = loop(tmp_path, root, kind, reviewer=None, opt_out="1", monkeypatch=monkeypatch)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 7\n")
    rep = asyncio.run(dl.release("seven", PLAN))
    assert rep["outcome"] == "REVIEW_UNAVAILABLE" and git(root, "rev-parse", "HEAD") == head0
    assert "no reviewer is wired" in rep["review"]["reasons"][0]
    kinds = [e["type"] for e in j.events(t)]
    assert "review.unavailable" in kinds and "commit.created" not in kinds
    assert (root / "backend" / "syrax" / "mod.py").read_text() != "VALUE = 7\n"  # rolled back


def test_a_conversation_release_with_no_reviewer_still_commits(tmp_path, monkeypatch):
    root = repo(tmp_path)
    j, t, dl = loop(tmp_path, root, "conversation", reviewer=None, opt_out="1", monkeypatch=monkeypatch)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 8\n")
    rep = asyncio.run(dl.release("eight", PLAN))
    assert rep["outcome"] == "COMMITTED"


def test_no_reviewer_with_the_services_opt_out_commits_as_before(tmp_path, monkeypatch):
    """The test suite (conftest: SYRAX_REVIEW=0) builds loops with no reviewer; the human's opt-out keeps them committing."""
    root = repo(tmp_path)
    j, t, dl = loop(tmp_path, root, "autonomous", reviewer=None, opt_out="0", monkeypatch=monkeypatch)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 3\n")
    rep = asyncio.run(dl.release("three", PLAN))
    assert rep["outcome"] == "COMMITTED" and "review" not in rep


async def skipper(info, summary, authors):
    return {"skipped": "SYRAX_REVIEW=0"}


def test_a_skip_without_the_services_opt_out_is_held(tmp_path, monkeypatch):
    root = repo(tmp_path)
    head0 = git(root, "rev-parse", "HEAD")
    j, t, dl = loop(tmp_path, root, "autonomous", reviewer=skipper, opt_out="1", monkeypatch=monkeypatch)
    os.environ["SYRAX_REVIEW"] = "0"  # set later, in the server process (a skill could): does not count
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 5\n")
    rep = asyncio.run(dl.release("five", PLAN))
    assert rep["outcome"] == "REVIEW_UNAVAILABLE" and git(root, "rev-parse", "HEAD") == head0
    assert "not started with SYRAX_REVIEW=0" in rep["review"]["reasons"][0]


def test_the_services_opt_out_at_start_still_skips(tmp_path, monkeypatch):
    root = repo(tmp_path)
    j, t, dl = loop(tmp_path, root, "autonomous", reviewer=skipper, opt_out="0", monkeypatch=monkeypatch)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 4\n")
    rep = asyncio.run(dl.release("four", PLAN))
    assert rep["outcome"] == "COMMITTED" and rep["review"] == {"skipped": "SYRAX_REVIEW=0"}
