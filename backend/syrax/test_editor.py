"""SyraxEditor: each test is a failure measured live on 2026-09-30."""

import asyncio
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

import pytest  # noqa: E402

from app.exceptions import ToolError  # noqa: E402
from syrax import editor as ed  # noqa: E402
from syrax.editor import SyraxEditor, find_loose, reindent  # noqa: E402


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


def test_missing_path_is_a_clear_error_not_a_type_error(tool):
    with pytest.raises(ToolError, match="`path` is required"):
        run(tool.execute(command="str_replace", old_str="a", new_str="b"))


def test_relative_paths_resolve_against_repo_backend_and_workspace(tool, tmp_path):
    f = tmp_path / "repo" / "backend" / "syrax" / "prompt.py"
    f.write_text("x = 1\n")
    out = run(tool.execute(command="view", path="backend/syrax/prompt.py"))
    assert "resolved to" in out and "x = 1" in out
    out = run(tool.execute(command="view", path="syrax\\prompt.py"))  # relative to backend, Windows separator
    assert "x = 1" in out
    out = run(tool.execute(command="create", path="notes/hello.txt", file_text="hi"))
    assert (tmp_path / "repo" / "backend" / "workspace" / "notes" / "hello.txt").read_text() == "hi"
    with pytest.raises(ToolError, match="not absolute and was not found"):
        run(tool.execute(command="view", path="nowhere/x.py"))


def test_create_overwrites_and_undo_restores(tool, tmp_path):
    f = tmp_path / "repo" / "backend" / "workspace" / "hello.txt"
    f.write_text("OLD")
    out = run(tool.execute(command="create", path=str(f), file_text="HELLO SYRAX"))
    assert "overwritten" in out and f.read_text() == "HELLO SYRAX"
    run(tool.execute(command="undo_edit", path=str(f)))
    assert f.read_text() == "OLD"


def test_view_range_past_the_end_is_clamped(tool, tmp_path):
    f = tmp_path / "repo" / "backend" / "workspace" / "c.py"
    f.write_text("count = 1\nname = 'x'\n")
    out = run(tool.execute(command="view", path=str(f), view_range=[1, 20]))
    assert "count = 1" in out and "name = 'x'" in out


def test_wrong_indentation_still_edits_once_and_reindents(tool, tmp_path):
    f = tmp_path / "repo" / "backend" / "workspace" / "c.py"
    f.write_text("def f():\n    count = 1\n    return count\n")
    out = run(tool.execute(command="str_replace", path=str(f), old_str="count = 1", new_str="count = 2"))
    assert f.read_text() == "def f():\n    count = 2\n    return count\n"  # exact text was there: normal path
    out = run(tool.execute(command="str_replace", path=str(f), old_str="  count = 2\n  return count", new_str="  count = 3\n  return count + 1"))
    assert "whitespace was ignored" in out
    assert f.read_text() == "def f():\n    count = 3\n    return count + 1\n"


def test_no_match_shows_the_nearest_lines(tool, tmp_path):
    f = tmp_path / "repo" / "backend" / "workspace" / "c.py"
    f.write_text("a = 1\nb = 2  # counter\n")
    with pytest.raises(ToolError, match="2: b = 2"):
        run(tool.execute(command="str_replace", path=str(f), old_str="b = 2\nc = 3", new_str="x"))


def test_loose_helpers():
    assert find_loose("x\n  y\n  z\n", "y\nz") == [1]
    assert find_loose("y\ny\n", "y") == [0, 1]
    assert reindent("a\n  b", "a", "    a") == "    a\n      b"


def test_view_on_a_directory_lists_it_without_unix_find(tool, tmp_path):
    """Live on Windows: 'FIND: Parameter format not correct'."""
    d = tmp_path / "repo" / "backend" / "syrax"
    (d / "sub").mkdir()
    (d / "a.py").write_text("x")
    (d / "sub" / "b.py").write_text("y")
    (d / "__pycache__").mkdir()
    out = run(tool.execute(command="view", path=str(d)))
    assert "a.py" in out and "b.py" in out and "__pycache__" not in out and "FIND" not in out
