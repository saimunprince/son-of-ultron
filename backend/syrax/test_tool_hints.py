"""Live 2026-10-14 (quality run #39): two kinds of call failed that need not
have. find_files with a folder and no pattern now lists the folder; asking the
editor to rename, move, copy or delete a file says which tool does that."""

import asyncio

import pytest

from syrax.desktop import DesktopControl
from syrax.editor import SyraxEditor
from app.exceptions import ToolError


def test_find_files_with_only_a_folder_lists_it(tmp_path):
    (tmp_path / "keep.txt").write_text("x")
    (tmp_path / "b.log").write_text("y")
    out = asyncio.run(DesktopControl().execute(action="find_files", target="", folder=str(tmp_path)))
    assert out.error is None and "keep.txt" in out.output and "b.log" in out.output
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "is empty" in asyncio.run(DesktopControl().execute(action="find_files", target="", folder=str(empty))).output
    none = asyncio.run(DesktopControl().execute(action="find_files", target="", folder=""))
    assert none.error and "a folder to list" in none.error


@pytest.mark.parametrize("cmd", ["rename", "move", "delete", "copy"])
def test_the_editor_says_which_tool_moves_files(tmp_path, cmd):
    f = tmp_path / "draft.txt"
    f.write_text("keep me\n")
    with pytest.raises(ToolError, match="use python_execute"):
        asyncio.run(SyraxEditor().execute(command=cmd, path=str(f)))
    assert f.read_text() == "keep me\n"
