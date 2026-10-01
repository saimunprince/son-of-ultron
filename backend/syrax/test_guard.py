"""python_execute cannot write SYRAX's journal or keys — not directly, not with
raw sqlite3, not from a Python process it spawns (all three were tried live)."""

import asyncio
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax.tools import AsyncPythonExecute  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def make_db(path: Path) -> None:
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE quality_runs(id INTEGER PRIMARY KEY, pass_rate REAL)")
    c.execute("INSERT INTO quality_runs(pass_rate) VALUES (90.0)")
    c.commit()
    c.close()


def run_tool(code: str) -> dict:
    return asyncio.new_event_loop().run_until_complete(AsyncPythonExecute().execute(code=code, timeout=60))


def test_python_execute_reads_but_cannot_write_the_journal(tmp_path, monkeypatch):
    db = tmp_path / "journal.db"
    make_db(db)
    monkeypatch.setenv("SYRAX_JOURNAL_FILE", str(db))
    read = run_tool(f"import sqlite3\nprint(sqlite3.connect(r'{db}').execute('select pass_rate from quality_runs').fetchone()[0])")
    assert read["success"] and "90.0" in read["observation"]
    write = run_tool(f"import sqlite3\nc = sqlite3.connect(r'{db}')\nc.execute('insert into quality_runs(pass_rate) values (100.0)')\nc.commit()\nprint('WROTE')")
    assert not write["success"] and "readonly" in write["observation"].lower()
    raw = run_tool(f"open(r'{db}', 'ab').write(b'x')\nprint('WROTE')")
    assert not raw["success"] and "only by the running core" in raw["observation"]
    gone = run_tool(f"import os\nos.remove(r'{db}')")
    assert not gone["success"] and db.exists()
    keys = run_tool(f"open(r'{tmp_path / 'brains.json'}', 'w').write('{{}}')")
    assert not keys["success"]  # the brain keys sit next to the journal
    assert sqlite3.connect(db).execute("select count(*) from quality_runs").fetchone()[0] == 1


def test_a_python_process_spawned_from_python_execute_is_guarded_too(tmp_path, monkeypatch):
    """Live: SYRAX ran `subprocess.run([sys.executable, '-c', ...])` to build a second core."""
    db = tmp_path / "journal.db"
    make_db(db)
    monkeypatch.setenv("SYRAX_JOURNAL_FILE", str(db))
    inner = f"import sqlite3; c = sqlite3.connect(r'{db}'); c.execute('insert into quality_runs(pass_rate) values (100.0)'); c.commit(); print('WROTE')"
    out = run_tool(
        "import subprocess, sys\n"
        f"r = subprocess.run([sys.executable, '-c', {inner!r}], capture_output=True, text=True, cwd=r'{BACKEND}')\n"
        "print(r.stdout, r.stderr)"
    )
    assert out["success"] and "WROTE" not in out["observation"] and "readonly" in out["observation"].lower()
    assert sqlite3.connect(db).execute("select count(*) from quality_runs").fetchone()[0] == 1


def test_other_files_are_untouched_by_the_guard(tmp_path, monkeypatch):
    db = tmp_path / "journal.db"
    make_db(db)
    monkeypatch.setenv("SYRAX_JOURNAL_FILE", str(db))
    f = tmp_path / "notes.txt"
    out = run_tool(f"open(r'{f}', 'w').write('ok')\nprint(open(r'{f}').read())")
    assert out["success"] and "ok" in out["observation"]
