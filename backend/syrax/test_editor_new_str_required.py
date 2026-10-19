"""Quality run #50 (self_patch_docs): the brain called str_replace with old_str = the whole of EXECUTION_PLAN.md and
file_text = the new file, without new_str. The upstream editor reads a missing new_str as "" and emptied the file;
the brain undid it two steps later. A str_replace without new_str now changes nothing and says what is missing."""

import asyncio

import pytest

from app.exceptions import ToolError
from syrax.editor import SyraxEditor
from syrax.journal import misuse


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_str_replace_without_new_str_changes_nothing(tmp_path):
    f = tmp_path / "plan.md"
    f.write_text("# Plan\n\nline one\n", encoding="utf-8")
    with pytest.raises(ToolError) as e:
        run(SyraxEditor().execute(command="str_replace", path=str(f), old_str="# Plan\n\nline one\n",
                                  file_text="# Plan\n\nline one\nProbe line.\n"))
    msg = str(e.value.message)
    assert msg.startswith("Parameter `new_str` is required for command: str_replace") and "file_text" in msg
    assert f.read_text(encoding="utf-8") == "# Plan\n\nline one\n"
    assert misuse("str_replace_editor", "Error: " + msg)  # the caller's mistake, not the tool's failure


def test_an_empty_new_str_still_deletes(tmp_path):
    f = tmp_path / "plan.md"
    f.write_text("keep\ndrop me\n", encoding="utf-8")
    run(SyraxEditor().execute(command="str_replace", path=str(f), old_str="drop me\n", new_str=""))
    assert f.read_text(encoding="utf-8") == "keep\n"
