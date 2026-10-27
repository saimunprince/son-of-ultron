"""An empty old_str is refused up front and nothing is written (eval task a6b54589a40d: on an empty file the edit
was applied, then reported failed with "empty separator", and the retry duplicated it)."""

import asyncio
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

import pytest  # noqa: E402

from app.exceptions import ToolError  # noqa: E402
from syrax import editor as ed  # noqa: E402
from syrax.editor import SyraxEditor  # noqa: E402


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def tool(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(ed, "BACKEND_ROOT", tmp_path / "repo" / "backend")
    monkeypatch.setattr(ed, "WORKSPACE", tmp_path / "repo" / "backend" / "workspace")
    (tmp_path / "repo" / "backend" / "workspace").mkdir(parents=True)
    t = SyraxEditor()
    t._file_history.clear()
    return t


@pytest.mark.parametrize("before", [b"", b"line one\nline two\n"])
def test_an_empty_old_str_is_refused_and_nothing_is_written(tool, tmp_path, before):
    f = tmp_path / "notes.txt"
    f.write_bytes(before)
    with pytest.raises(ToolError) as e:
        run(tool.execute(command="str_replace", path=str(f), old_str="", new_str="hello\n"))
    msg = str(e.value)
    assert "`old_str` is empty" in msg and "create" in msg and "insert" in msg and "Nothing was changed" in msg
    assert f.read_bytes() == before
    assert not tool._file_history[str(f)]
