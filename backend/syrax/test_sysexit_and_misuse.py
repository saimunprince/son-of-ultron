"""Live 2026-10-14 (objective 232): SYRAX ran `pytest.main([...])` and then
`sys.exit(code)` three times in python_execute and got an empty observation
each time; the pytest report was lost. The output is kept and the exit named
(the call still did not finish). And five more caller mistakes of the last
five days are told from tool failures: an editor command that does not exist,
a directory given to the editor, find_files without a pattern, learn
without a source."""

import asyncio

from syrax.journal import misuse
from syrax.tools import AsyncPythonExecute


def run(code):
    return asyncio.new_event_loop().run_until_complete(AsyncPythonExecute().execute(code=code, timeout=60))


def test_output_before_sys_exit_is_kept():
    out = run("print('3 passed, 1 failed')\nimport sys\nsys.exit(1)")
    assert out["success"] is False
    assert out["observation"].startswith("3 passed, 1 failed") and "sys.exit(1)" in out["observation"]


def test_more_caller_mistakes_are_not_tool_failures():
    assert misuse("str_replace_editor", "Error: Unrecognized command undo. The allowed commands for the str_replace_editor tool are: view")
    assert misuse("str_replace_editor", "Error: The path C:\\ws\\p4 is a directory and only the `view` command can be used on directories")
    assert misuse("str_replace_editor", "Error: The path backend/x.py is not absolute and was not found under C:\\repo")
    assert misuse("desktop", "Error: find_files needs a name pattern in target.")
    assert misuse("learn", "Error: learn refused: cite at least one knowledge_id or URL")
    assert not misuse("desktop", "Error")
    assert not misuse("learn", "Error: the knowledge store is unavailable")
