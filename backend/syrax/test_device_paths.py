r"""Review 2026-10-27: \\?\C:\..., \\.\C:\... and \\localhost\C$\... name the same file as C:\..., but every check
compared strings, so an autonomous str_replace_editor create of backend\\config\\brains.json was allowed under those
spellings (plain, forward-slash, upper-case and `..` spellings were refused), and python_execute could write the
journal through them. Paths are now read in their plain form first; an administrative share is never written, and
SYRAX's own work writes no network path at all."""

import asyncio
import os
import sqlite3
import sys

import pytest

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax import editor, guard, permissions as P  # noqa: E402
from syrax.journal import BACKEND_ROOT  # noqa: E402
from syrax.tools import AsyncPythonExecute  # noqa: E402

BS = "\\"
KEYS = str(BACKEND_ROOT / "config" / "brains.json")
windows = pytest.mark.skipif(sys.platform != "win32", reason="Win32 path spellings")


def spellings(plain: str) -> dict:
    return {"extended": BS * 2 + "?" + BS + plain, "device": BS * 2 + "." + BS + plain,
            "admin-share": BS * 2 + "localhost" + BS + plain[0] + "$" + plain[2:],
            "unc-extended": BS * 2 + "?" + BS + "UNC" + BS + "localhost" + BS + plain[0] + "$" + plain[2:]}


def verdict(path: str, kind: str = "autonomous"):
    d = P.classify("str_replace_editor", {"command": "create", "path": path, "file_text": "x"})
    return P.decide(d, kind, "do something")


@windows
def test_canonical_path_turns_this_machines_spellings_into_the_drive_path():
    plain = r"C:\ai-agent\x\brains.json"
    for name, s in spellings(plain).items():
        assert guard.canonical_path(s) == plain, name
    assert guard.canonical_path(r"\\fileserver\docs\a.txt") == r"\\fileserver\docs\a.txt"  # another machine: unchanged
    assert guard.canonical_path(plain) == plain


@windows
@pytest.mark.parametrize("kind", ["autonomous", "eval", "conversation"])
def test_the_keys_are_refused_under_every_spelling(kind):
    assert verdict(KEYS, kind).action == "refuse"
    for name, s in spellings(KEYS).items():
        assert verdict(s, kind).action == "refuse", (name, kind)


@windows
def test_network_paths_are_refused_for_own_work_and_admin_shares_for_everyone():
    share = r"\\fileserver\docs\notes.txt"
    assert verdict(share, "autonomous").action == "refuse"
    assert verdict(r"\\10.0.0.5\C$\x.txt", "conversation").action == "refuse"
    assert verdict(share, "conversation").action != "refuse"  # a human may ask for a file on a share


@windows
def test_the_editor_resolves_a_device_spelling_to_the_plain_path():
    p, _ = editor.resolve_path(BS * 2 + "?" + BS + KEYS, "create")
    assert str(p) == KEYS


@windows
def test_python_execute_cannot_write_the_journal_through_a_device_path(tmp_path, monkeypatch):
    db = tmp_path / "journal.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE t(x)")
    c.commit()
    c.close()
    monkeypatch.setenv("SYRAX_JOURNAL_FILE", str(db))
    for name, s in spellings(str(db)).items():
        code = f"open(r'{s}', 'ab').write(b'x')\nprint('WROTE')"
        out = asyncio.new_event_loop().run_until_complete(AsyncPythonExecute().execute(code=code, timeout=60))
        assert not out["success"] and "WROTE" not in out["observation"], (name, out["observation"][-300:])
    assert db.read_bytes()[-1:] != b"x"
