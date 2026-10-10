"""The editor keeps a file's line endings: an LF file stays LF (and an edit
undone gives back the same bytes), a CRLF file stays CRLF, a new file is LF."""

import asyncio
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

import pytest  # noqa: E402

from syrax import editor as ed  # noqa: E402
from syrax.editor import SyraxEditor  # noqa: E402


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def tool(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(ed, "BACKEND_ROOT", tmp_path / "repo" / "backend")
    monkeypatch.setattr(ed, "WORKSPACE", tmp_path / "repo" / "backend" / "workspace")
    (tmp_path / "repo" / "backend" / "syrax").mkdir(parents=True)
    (tmp_path / "repo" / "backend" / "workspace").mkdir()
    t = SyraxEditor()
    t._file_history.clear()
    return t


def test_lf_file_stays_lf_and_undo_gives_back_the_same_bytes(tool, tmp_path):
    f = tmp_path / "repo" / "backend" / "syrax" / "mod.py"
    original = b"def a():\n    return 1\n\n\ndef b():\n    return 2\n"
    f.write_bytes(original)
    run(tool.execute(command="str_replace", path=str(f), old_str="return 1", new_str="return 10"))
    assert b"\r\n" not in f.read_bytes() and b"return 10" in f.read_bytes()
    run(tool.execute(command="undo_edit", path=str(f)))
    assert f.read_bytes() == original


def test_crlf_file_stays_crlf(tool, tmp_path):
    f = tmp_path / "repo" / "backend" / "syrax" / "win.py"
    f.write_bytes(b"x = 1\r\ny = 2\r\n")
    run(tool.execute(command="insert", path=str(f), insert_line=1, new_str="z = 3"))
    data = f.read_bytes()
    assert data.count(b"\r\n") == 3 and b"\n" not in data.replace(b"\r\n", b"")


def test_a_new_file_is_lf(tool, tmp_path):
    f = tmp_path / "repo" / "backend" / "syrax" / "new.py"
    run(tool.execute(command="create", path=str(f), file_text="a = 1\nb = 2\n"))
    assert f.read_bytes() == b"a = 1\nb = 2\n"
