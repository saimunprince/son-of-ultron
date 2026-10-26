"""The python_execute worker starts from syrax._pyexec_child, which imports only the standard library and the guard:
a worker started from AsyncPythonExecute._guarded_run imported syrax.tools, app.tool and pydantic first (0.7-1.0 s per
call against 0.04 s for a bare interpreter, profiled 2026-10-26)."""

import asyncio
import ast
from pathlib import Path

from syrax.devloop import JUDGES
from syrax.tools import AsyncPythonExecute

CHILD = Path(__file__).with_name("_pyexec_child.py")


def run(code: str, timeout: int = 60) -> dict:
    return asyncio.run(AsyncPythonExecute().execute(code, timeout=timeout))


def test_the_worker_does_not_import_app_or_pydantic():
    r = run("import sys; print('pydantic' in sys.modules, 'app.tool' in sys.modules, 'syrax.tools' in sys.modules)")
    assert r == {"observation": "False False False\n", "success": True}


def test_the_worker_still_installs_the_guard_and_the_preloads():
    r = run("import builtins; print(getattr(builtins, '_syrax_guard', False), os.sep == os.path.sep, Path is pathlib.Path)")
    assert r == {"observation": "True True True\n", "success": True}


def test_the_worker_entry_imports_only_the_standard_library_at_module_level():
    tree = ast.parse(CHILD.read_text(encoding="utf-8"))
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            top.add((node.module or "").split(".")[0])
    assert top <= {"sys", "io", "typing"}, top


def test_the_worker_module_is_a_judge():
    assert "backend/syrax/_pyexec_child.py" in JUDGES


def test_the_process_target_is_the_light_entry():
    src = (Path(__file__).with_name("tools.py")).read_text(encoding="utf-8")
    assert "multiprocessing.Process(target=guarded_run," in src and "target=self._guarded_run" not in src
