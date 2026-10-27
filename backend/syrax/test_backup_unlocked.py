"""The daily backup does not hold the journal lock for the copy. It held it for the whole online copy (~150 MB),
and the sync reads on the event loop (task(), events(), get_meta()) take that lock: the backup froze the loop.
Under WAL the copy reads one consistent snapshot through its own connection, while writes go on."""

import sqlite3
import threading
from pathlib import Path

from syrax.journal import Journal


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)


def test_the_copy_does_not_wait_on_the_journal_lock(tmp_path):
    j = Journal(tmp_path / "journal.db")
    t = j.start_task_sync("a task")
    j.record_sync("final", {"content": "done"}, task_id=t)
    out = tmp_path / "copy" / "journal.db"
    done = threading.Event()
    copier = threading.Thread(target=lambda: (j.backup_to(out), done.set()), daemon=True)
    with j._lock:  # whatever the loop holds the lock for, the copy runs beside it
        copier.start()
        copied = done.wait(10)
    copier.join(10)
    assert copied, "backup_to waited on the journal lock"
    with ro(out) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == j.count("events") >= 2
    j.close()


def test_a_copy_beside_writes_is_one_consistent_committed_state(tmp_path):
    j = Journal(tmp_path / "journal.db")
    big = "x" * 20000
    for i in range(300):
        j.record_sync("think", {"i": i, "pad": big})
    stop = threading.Event()

    def write():
        n = 0
        while not stop.is_set():
            t = j.start_task_sync(f"task {n}")
            j.record_sync("final", {"content": "done"}, task_id=t)
            n += 1

    w = threading.Thread(target=write, daemon=True)
    w.start()
    try:
        out = tmp_path / "copy" / "journal.db"
        j.backup_to(out)
    finally:
        stop.set()
        w.join(10)
    with ro(out) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        tasks = c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        # every task in the copy has its committed events: a snapshot, never half a write
        started = c.execute("SELECT COUNT(DISTINCT task_id) FROM events WHERE task_id IS NOT NULL").fetchone()[0]
        assert started == tasks
    j.close()
