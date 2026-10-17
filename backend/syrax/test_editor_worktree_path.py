import asyncio

import pytest

from app.exceptions import ToolError
from syrax import editor as ed
from syrax.editor import SyraxEditor


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_a_worktree_path_to_an_untracked_file_reads_the_running_tree(tmp_path, monkeypatch):
    live, wt = tmp_path / "live", tmp_path / "live" / ".syrax" / "worktrees" / "t1"
    kept = live / "backend" / "config" / "rollback" / "1792227608-5218b36.patch"
    kept.parent.mkdir(parents=True)
    kept.write_text("--- a/backend/syrax/memory.py\n+++ b/backend/syrax/memory.py\n")
    (wt / "backend").mkdir(parents=True)
    monkeypatch.setattr(ed, "ROOT_MAP", (live, wt))
    asked = wt / "backend" / "config" / "rollback" / "1792227608-5218b36.patch"
    out = run(SyraxEditor().execute(command="view", path=str(asked)))
    assert "+++ b/backend/syrax/memory.py" in out and "read from the running tree" in out
    with pytest.raises(ToolError) as e:
        run(SyraxEditor().execute(command="str_replace", path=str(asked), old_str="memory", new_str="other"))
    assert "not in this task's worktree" in str(e.value.message)
    assert kept.read_text().count("memory.py") == 2  # the running tree is untouched
