"""SYRAX backups: a verified copy of the evidence, put back only by a human.

Why. backend/config/journal.db is everything SYRAX knows about what it did: tasks, events, verifications,
objectives, knowledge, skills (152 MB on 2026-10-25). brains.json holds the API keys, memory.json the
human's facts, config.toml the model and tool settings. None of the four is in git, and the journal was
lost once already when the project moved to Windows (2026-09-30). A copy nobody ever opened is a hope,
not a backup, so every snapshot is verified (integrity_check, row counts, sha256 of every file) and the
restore path is tested (test_backup.py).

What is copied, into backend/config/backups/<YYYYMMDD-HHMMSS>/ (a ``backups`` folder beside the journal):
  journal.db      through sqlite3's online backup API on the journal's own connection: consistent under
                  WAL while SYRAX keeps writing; the copy is a plain rollback-journal file (no -wal/-shm)
  brains.json     the API keys. THE FOLDER HOLDS SECRETS: the manifest says so and the folder is gitignored
  memory.json, config.toml
  manifest.json   {created, git_head, secrets, files: {name: {bytes, sha256}}, journal: {tasks, events,
                  objectives, integrity}}

What is never copied: ws.token (auth.token() writes a new one on first use), mcp.json (hand-made from
mcp.example.json, holds no state), history.jsonl, the workspace, skills, logs, rollback patches, and the
journal's -wal/-shm sidecars (the backup API folds the WAL into the copy).

When: the autonomy cycle, idle and once a day (meta ``last_backup``), before journal maintenance prunes
anything; by hand with ``python syrax.py --backup``. The newest KEEP snapshots stay; an older folder is
pruned only when it is named like a stamp and holds a manifest, nothing else in the folder is touched.

Restore is a human act: ``python syrax.py --restore backend/config/backups/<stamp>``. It refuses while
SYRAX runs (pid file, backend port, a live owner of the journal), refuses a snapshot that does not verify,
moves the current files aside to backups/_replaced-<stamp>/ and copies the snapshot in. No agent tool
exposes snapshot or restore and none may be added: an agent that can put an older journal back can erase
the evidence of its own work. Stdlib only, like the journal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from syrax.journal import BACKEND_ROOT, DEFAULT_FILE, Journal, JournalError, _owned_elsewhere

log = logging.getLogger("syrax.backup")

BACKUP_ROOT = BACKEND_ROOT / "config" / "backups"
KEEP = 7
EVERY_S = 86400.0
JOURNAL_NAME = "journal.db"
CONFIG_FILES = ("brains.json", "memory.json", "config.toml")
MANIFEST = "manifest.json"
COUNTED = ("tasks", "events", "objectives")
STAMP_RE = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
SECRETS_NOTE = "brains.json holds the API keys: keep this folder private, never commit or share it"
# the launcher's marks of a running SYRAX (syrax.py: PID_FILE, BACKEND_PORT)
PID_FILE = BACKEND_ROOT.parent / "syrax.pid"
BACKEND_PORT = int(os.getenv("SYRAX_PORT", "8765"))


class BackupError(RuntimeError):
    """A snapshot or restore that could not be made true."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_head(repo: Path) -> Optional[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def _stamp(now: float) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(now))


def _stamp_dir(root: Path, now: float) -> Path:
    stamp = _stamp(now)
    d, n = root / stamp, 1
    while d.exists():  # two snapshots in one second
        d = root / f"{stamp}-{n}"
        n += 1
    return d


def _inspect(db_path: Path) -> dict:
    """Row counts and integrity of a copied journal, read-only; a copy that cannot be read says so instead of raising."""
    out: dict = {t: None for t in COUNTED}
    try:
        con = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        out["integrity"] = f"cannot open: {e}"
        return out
    try:
        rows = con.execute("PRAGMA integrity_check").fetchall()
        out["integrity"] = "ok" if [r[0] for r in rows] == ["ok"] else "; ".join(str(r[0]) for r in rows)[:500]
        for t in COUNTED:
            out[t] = int(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    except sqlite3.Error as e:
        out["integrity"] = f"error: {e}"
    finally:
        con.close()
    return out


def _journal_write(journal: Journal, type_: str, payload: dict, done_at: Optional[float] = None) -> bool:
    """Record the outcome in the journal when this handle may write (a second process beside a running
    SYRAX holds a read-only one). True when it was journaled."""
    if getattr(journal, "read_only", False):
        return False
    try:
        journal.record_sync(type_, payload)
        if done_at is not None:
            journal.set_meta("last_backup", str(done_at))
    except (sqlite3.Error, JournalError) as e:
        log.warning(f"could not journal {type_}: {e}")
        return False
    return True


def snapshot(journal: Journal, dest_root: Optional[Path | str] = None, config_dir: Optional[Path | str] = None,
             now: Optional[float] = None) -> dict:
    """One verified copy of the journal and the config files beside it into dest_root/<stamp>/.

    config_dir defaults to the journal's folder (backend/config for the live one); dest_root to
    config_dir/backups. Returns the manifest plus ``dir``, ``bytes`` and ``journaled``. On success the
    journal gets meta ``last_backup`` and a ``backup.completed`` event; on failure the half-written folder
    is removed, ``backup.failed {error}`` is journaled and the error is raised."""
    now = now or time.time()
    config_dir = Path(config_dir) if config_dir else Path(journal.path).parent
    root = Path(dest_root) if dest_root else config_dir / "backups"
    d = _stamp_dir(root, now)
    try:
        d.mkdir(parents=True, exist_ok=False)
        journal.backup_to(d / JOURNAL_NAME)
        for name in CONFIG_FILES:
            src = config_dir / name
            if src.is_file():
                shutil.copy2(src, d / name)
        files: Dict[str, dict] = {p.name: {"bytes": p.stat().st_size, "sha256": _sha256(p)} for p in sorted(d.iterdir()) if p.is_file()}
        info = _inspect(d / JOURNAL_NAME)
        if info["integrity"] != "ok":
            raise BackupError(f"the copy did not pass integrity_check: {info['integrity']}")
        manifest = {
            "created": now,
            "created_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            "git_head": _git_head(BACKEND_ROOT.parent),
            "source": str(Path(journal.path).resolve()),
            "secrets": "brains.json" in files,
            "note": SECRETS_NOTE if "brains.json" in files else "no brains.json was beside the journal",
            "bytes": sum(f["bytes"] for f in files.values()),
            "files": files,
            "journal": info,
        }
        (d / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as e:
        shutil.rmtree(d, ignore_errors=True)  # a half-written folder must never look like a backup
        _journal_write(journal, "backup.failed", {"error": f"{type(e).__name__}: {e}", "dir": str(d)})
        raise
    manifest["dir"] = str(d)
    manifest["journaled"] = _journal_write(
        journal, "backup.completed",
        {"dir": str(d), "bytes": manifest["bytes"], "files": sorted(files), "integrity": info["integrity"], **{t: info[t] for t in COUNTED}},
        done_at=now,
    )
    return manifest


def verify(dir: Path | str) -> dict:
    """Is this folder a backup that would restore what its manifest promises? Every file's size and
    sha256, the copied journal's integrity_check and its row counts are checked against the manifest."""
    d = Path(dir)
    problems: List[str] = []
    try:
        manifest = json.loads((d / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"ok": False, "dir": str(d), "problems": [f"no readable {MANIFEST}: {e}"], "journal": None, "created": None}
    files = manifest.get("files") or {}
    if JOURNAL_NAME not in files:
        problems.append(f"the manifest lists no {JOURNAL_NAME}")
    for name, want in files.items():
        p = d / name
        if not p.is_file():
            problems.append(f"{name}: missing")
            continue
        size = p.stat().st_size
        if size != want.get("bytes"):
            problems.append(f"{name}: {size} bytes, the manifest says {want.get('bytes')}")
        digest = _sha256(p)
        if digest != want.get("sha256"):
            problems.append(f"{name}: sha256 {digest[:12]} differs from the manifest's {str(want.get('sha256'))[:12]}")
    info = None
    if (d / JOURNAL_NAME).is_file():
        info = _inspect(d / JOURNAL_NAME)
        if info["integrity"] != "ok":
            problems.append(f"{JOURNAL_NAME}: integrity_check: {info['integrity']}")
        want = manifest.get("journal") or {}
        for t in COUNTED:
            if info.get(t) != want.get(t):
                problems.append(f"{JOURNAL_NAME}: {info.get(t)} {t}, the manifest says {want.get(t)}")
    return {"ok": not problems, "dir": str(d), "problems": problems, "journal": info, "created": manifest.get("created")}


def snapshots(root: Path | str) -> List[Path]:
    """The snapshot folders under root, oldest first: named like a stamp and holding a manifest. Nothing else counts."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and STAMP_RE.match(p.name) and (p / MANIFEST).is_file())


def prune(root: Path | str, keep: int = KEEP) -> List[str]:
    """Remove the oldest snapshots beyond `keep` (never below one). Returns the folders removed."""
    keep = max(1, int(keep))
    gone: List[str] = []
    for p in snapshots(root)[:-keep]:
        shutil.rmtree(p)
        gone.append(str(p))
    return gone


def due(journal: Journal, every_s: float = EVERY_S, now: Optional[float] = None) -> bool:
    """A snapshot is due when none was journaled yet or the last one is older than every_s (meta ``last_backup``)."""
    last = journal.get_meta("last_backup")
    if last is None:
        return True
    try:
        return (now or time.time()) - float(last) >= every_s
    except (TypeError, ValueError):
        return True


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def running(config_dir: Optional[Path | str] = None) -> Optional[str]:
    """Why SYRAX counts as running, or None: the launcher's pid file, something on the backend port, or
    another live process owning the journal (the same owner lock Journal uses)."""
    if PID_FILE.exists():
        try:
            pid = PID_FILE.read_text().strip() or "?"
        except OSError:
            pid = "?"
        return f"{PID_FILE} exists (pid {pid}); stop SYRAX first: python syrax.py --stop"
    if port_in_use(BACKEND_PORT):
        return f"something answers on port {BACKEND_PORT}"
    jp = (Path(config_dir) if config_dir else DEFAULT_FILE.parent) / JOURNAL_NAME
    if _owned_elsewhere(jp):
        return f"another live process owns {jp}"
    return None


def restore(dir: Path | str, config_dir: Optional[Path | str] = None, now: Optional[float] = None) -> dict:
    """Put a verified snapshot back into config_dir (backend/config). Refuses while SYRAX runs and when
    verify() finds a problem; otherwise moves the current files (and the journal's -wal/-shm) aside to
    config_dir/backups/_replaced-<stamp>/, copies the snapshot's files in and checks their sha256 again.
    Not a tool and never to become one: a human runs ``python syrax.py --restore <dir>``."""
    d = Path(dir)
    config_dir = Path(config_dir) if config_dir else DEFAULT_FILE.parent
    v = verify(d)
    if not v["ok"]:
        return {"ok": False, "dir": str(d), "restored": [], "problems": ["the snapshot does not verify; nothing was touched"] + v["problems"]}
    why = running(config_dir)
    if why:
        return {"ok": False, "dir": str(d), "restored": [], "problems": [f"SYRAX is running ({why}); nothing was touched"]}
    manifest = json.loads((d / MANIFEST).read_text(encoding="utf-8"))
    names = [n for n in manifest["files"] if n != MANIFEST]
    aside = config_dir / "backups" / f"_replaced-{_stamp(now or time.time())}"
    aside.mkdir(parents=True, exist_ok=True)
    replaced: List[str] = []
    for name in names + [JOURNAL_NAME + "-wal", JOURNAL_NAME + "-shm"]:
        cur = config_dir / name
        if cur.exists():
            shutil.move(str(cur), str(aside / name))
            replaced.append(name)
    if not replaced:
        aside.rmdir()
    restored: List[str] = []
    for name in names:
        shutil.copy2(d / name, config_dir / name)
        if _sha256(config_dir / name) != manifest["files"][name]["sha256"]:
            raise BackupError(f"{name} did not copy back intact; the previous files are in {aside}")
        restored.append(name)
    try:
        os.chmod(config_dir / JOURNAL_NAME, 0o600)
    except OSError:
        pass
    return {"ok": True, "dir": str(d), "restored": restored, "replaced": replaced, "replaced_to": str(aside) if replaced else None,
            "journal": v["journal"]}


# ——— command line (python -m syrax.backup; the launcher's --backup / --restore call this) ———

def _mb(n: int) -> str:
    return f"{n / 1e6:.1f} MB"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m syrax.backup", description="Verified backups of the SYRAX journal and config files.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--snapshot", action="store_true", help=f"copy journal.db, {', '.join(CONFIG_FILES)} into backups/<stamp>, verify, prune to --keep")
    g.add_argument("--verify", metavar="DIR", help="check a snapshot folder against its manifest")
    g.add_argument("--restore", metavar="DIR", help="put a snapshot back into backend/config (SYRAX must be stopped)")
    ap.add_argument("--keep", type=int, default=KEEP, help=f"snapshots to keep after --snapshot (default {KEEP})")
    ap.add_argument("--root", metavar="DIR", help="where snapshots go (default: a backups folder beside the journal)")
    a = ap.parse_args(argv)
    if a.snapshot:
        path = Path(os.getenv("SYRAX_JOURNAL_FILE", str(DEFAULT_FILE)))
        if not path.exists():
            print(f"SYRAX backup: no journal at {path}")
            return 1
        j = Journal(path, recover=False)  # beside a running SYRAX this handle is read-only: the copy still happens
        try:
            m = snapshot(j, dest_root=a.root)
        except Exception as e:
            print(f"SYRAX backup: failed: {e}")
            return 1
        finally:
            j.close()
        v = verify(m["dir"])
        gone = prune(Path(m["dir"]).parent, a.keep) if v["ok"] else []
        info = m["journal"]
        print(f"SYRAX backup: {m['dir']} ({_mb(m['bytes'])}, {len(m['files'])} files; {info['tasks']} tasks, {info['events']} events, "
              f"{info['objectives']} objectives; git {str(m.get('git_head'))[:12]})")
        print("verified: ok" if v["ok"] else "verified: FAILED: " + "; ".join(v["problems"]))
        if gone:
            print(f"pruned {len(gone)} older snapshot(s), {a.keep} kept")
        if m["secrets"]:
            print(f"note: {SECRETS_NOTE}")
        if not m["journaled"]:
            print("note: SYRAX is running, so this copy was made read-only and is not journaled; the running SYRAX keeps its own daily backup")
        return 0 if v["ok"] else 1
    if a.verify:
        v = verify(a.verify)
        print(f"SYRAX backup: {a.verify}: " + ("ok" if v["ok"] else "FAILED: " + "; ".join(v["problems"])))
        return 0 if v["ok"] else 1
    r = restore(a.restore)
    if not r["ok"]:
        print("SYRAX restore: refused: " + "; ".join(r["problems"]))
        return 1
    info = r["journal"] or {}
    print(f"SYRAX restore: {', '.join(r['restored'])} restored from {r['dir']} ({info.get('tasks')} tasks, {info.get('events')} events, "
          f"{info.get('objectives')} objectives)")
    if r["replaced_to"]:
        print(f"the previous files were moved to {r['replaced_to']}")
    print("start SYRAX again: python syrax.py")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
