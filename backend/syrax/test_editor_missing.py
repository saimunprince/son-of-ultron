"""A path that is not there: the error names the files with that name, and an
isolated task reads an untracked file (a skill) from the running tree but
cannot change it there. Live 2026-10-12: all 13 of the editor's latest
failures were missing paths, most of them guessed."""

import asyncio

import pytest

from app.exceptions import ToolError
from syrax import editor as ed
from syrax.editor import SyraxEditor


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_a_wrong_path_names_the_real_file(tmp_path, monkeypatch):
    real = tmp_path / "backend" / "app" / "tool" / "str_replace_editor.py"
    real.parent.mkdir(parents=True)
    real.write_text("x = 1\n")
    (tmp_path / "frontend" / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "frontend" / "node_modules" / "pkg" / "str_replace_editor.py").write_text("skip me")
    monkeypatch.setattr(ed, "REPO_ROOT", tmp_path)
    guess = tmp_path / "backend" / "syrax" / "app" / "tool" / "str_replace_editor.py"
    with pytest.raises(ToolError) as e:
        run(SyraxEditor().execute(command="view", path=str(guess)))
    assert str(e.value.message) == f"The path {guess} does not exist. Files with that name: {real}."
    with pytest.raises(ToolError) as e:
        run(SyraxEditor().execute(command="str_replace", path=str(tmp_path / "nothing.py"), old_str="a", new_str="b"))
    assert "No file named nothing.py exists in the repository." in str(e.value.message)


def test_an_isolated_task_reads_an_untracked_skill_but_cannot_change_it(tmp_path, monkeypatch):
    live, wt = tmp_path / "live", tmp_path / "live" / ".syrax" / "worktrees" / "t1"
    skill = live / "backend" / "skills" / "screen_brightness" / "skill.py"
    skill.parent.mkdir(parents=True)
    skill.write_text("LEVEL = 50\n")
    (wt / "backend").mkdir(parents=True)
    monkeypatch.setattr(ed, "ROOT_MAP", (live, wt))
    out = run(SyraxEditor().execute(command="view", path=str(skill)))
    assert "LEVEL = 50" in out and "read from the running tree" in out
    with pytest.raises(ToolError) as e:
        run(SyraxEditor().execute(command="str_replace", path=str(skill), old_str="50", new_str="60"))
    assert "not in this task's worktree" in str(e.value.message) and "skill_create" in str(e.value.message)
    assert skill.read_text() == "LEVEL = 50\n"  # the running tree is untouched
