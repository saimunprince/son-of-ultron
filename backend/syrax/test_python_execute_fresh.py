"""python_execute, as brains use it (live 2026-10-11, objective 117): common
modules are already imported in every fresh call, an error names its type, and
a call that succeeded is not counted as failed because its output shows a
traceback of a test it ran."""

import asyncio

from syrax.agent import _succeeded
from syrax.tools import PRELOADED, AsyncPythonExecute


def run(code):
    return asyncio.new_event_loop().run_until_complete(AsyncPythonExecute().execute(code=code, timeout=60))


def test_common_modules_are_already_there_in_a_fresh_call():
    out = run("print(os.sep in os.path.join('a', 'b'), json.dumps([1]), Path('x/y.txt').name, re.sub('a', 'b', 'a'), "
              "math.floor(2.5), type(datetime.date.today()).__name__, callable(subprocess.run), callable(shutil.copy))")
    assert out == {"observation": "True [1] y.txt b 2 date True True\n", "success": True}


def test_an_error_names_its_type_and_nothing_carries_over():
    assert run("y = 1\nprint(y)") == {"observation": "1\n", "success": True}
    out = run("print(y)")
    assert out == {"observation": "NameError: name 'y' is not defined", "success": False}
    assert run("raise ValueError('bad input')") == {"observation": "ValueError: bad input", "success": False}


def test_the_tool_says_every_call_starts_fresh():
    text = AsyncPythonExecute().parameters["properties"]["code"]["description"]
    assert "starts fresh" in text and all(m in text for m in PRELOADED)


def wrapped(d):
    return "Observed output of cmd `python_execute` executed:\n" + repr(d)


def test_a_printed_traceback_of_a_test_the_code_ran_is_output_not_failure():
    ok = wrapped({"observation": "stdout: \nstderr: Traceback (most recent call last):\n  File \"check.py\", line 3\nAssertionError: 4\n", "success": True})
    assert _succeeded(ok)
    assert not _succeeded(wrapped({"observation": "NameError: name 'os' is not defined", "success": False}))
    assert not _succeeded(wrapped({"observation": "Error: the python_execute worker exited with code 1 before returning a result", "success": False}))
    assert not _succeeded("Error: refused: deletes files (DESTRUCTIVE) is not done in autonomous work")
    assert _succeeded("Observed output of cmd `str_replace_editor` executed:\nFile created successfully")
