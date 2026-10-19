"""Live 2026-10-19 (quality run #51, self_map_protected): two python_execute calls walked the whole repository,
.venv included, and were stopped at 60 s with "Execution timeout after 60 seconds" and nothing else; what they had
printed was lost. So was everything a code printed before it raised. Both are kept now; a code that printed nothing
gets the short answers it always got."""

import asyncio

from syrax.tools import AsyncPythonExecute


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_output_printed_before_a_timeout_is_kept():
    out = run(AsyncPythonExecute().execute(code="import time\nprint('walked 3 of 9 folders')\ntime.sleep(30)", timeout=3))
    assert out["success"] is False
    assert out["observation"].startswith("Execution timeout after 3 seconds; it printed this before it was stopped:")
    assert out["observation"].endswith("walked 3 of 9 folders\n")


def test_output_printed_before_an_exception_is_kept():
    out = run(AsyncPythonExecute().execute(code="print('step 1 done')\nraise ValueError('bad row 7')", timeout=60))
    assert out == {"observation": "step 1 done\nValueError: bad row 7", "success": False}
    out = run(AsyncPythonExecute().execute(code="print('no newline', end='')\n1 / 0", timeout=60))
    assert out["observation"] == "no newline\nZeroDivisionError: division by zero"


def test_a_code_that_printed_nothing_gets_the_short_answers():
    assert run(AsyncPythonExecute().execute(code="import time\ntime.sleep(30)", timeout=1)) == {
        "observation": "Execution timeout after 1 seconds", "success": False}
    assert run(AsyncPythonExecute().execute(code="int('x')", timeout=60)) == {
        "observation": "ValueError: invalid literal for int() with base 10: 'x'", "success": False}
