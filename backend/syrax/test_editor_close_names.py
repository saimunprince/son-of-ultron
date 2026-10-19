"""Quality run #48 (fix_import): app.py imported `helpers`, the folder held helperz.py, and the editor answered only
"No file named helpers.py exists in the repository"; the brain wrote a new helpers.py with its own greeting instead
of fixing the import. The error now names the files whose name is close."""

import asyncio

import pytest

from app.exceptions import ToolError
from syrax import editor as ed
from syrax.editor import SyraxEditor


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_a_missing_name_lists_close_names(tmp_path, monkeypatch):
    imp = tmp_path / "backend" / "workspace" / "imp"
    imp.mkdir(parents=True)
    (imp / "helperz.py").write_text("def greet(n):\n    return 'hello ' + n\n")
    (imp / "helpers.txt").write_text("another suffix\n")
    (imp / "unrelated.py").write_text("x = 1\n")
    monkeypatch.setattr(ed, "REPO_ROOT", tmp_path)
    asked = tmp_path / "backend" / "workspace" / "helpers.py"
    with pytest.raises(ToolError) as e:
        run(SyraxEditor().execute(command="view", path=str(asked)))
    assert str(e.value.message) == (f"The path {asked} does not exist. No file named helpers.py exists in the repository. "
                                    f"Close names: {imp / 'helperz.py'}.")
    assert ed.close_names(asked, tmp_path) == [str(imp / "helperz.py")]

