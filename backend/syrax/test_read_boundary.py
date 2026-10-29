"""2026-10-29: the kernel boundary around SYRAX's own code limited writes only, so its python_execute could still read
backend/config: the brain keys (brains.json), the journal and the UI token. Now own work reads only the system, the
interpreter and venv, harmless git config and the repository except backend/config (whose file names may show, not
their contents); ordinary work, imports of SYRAX's own modules included, still runs."""

import asyncio

import pytest

from syrax import _confine, tools
from syrax.journal import BACKEND_ROOT

needs_landlock = pytest.mark.skipif(_confine.abi() < 1, reason="Landlock is not available on this system")


def run(code: str) -> dict:
    return asyncio.new_event_loop().run_until_complete(tools.AsyncPythonExecute().execute(code=code, timeout=60))


@pytest.fixture
def own_work(monkeypatch):
    monkeypatch.setattr(tools, "TASK_KIND", "autonomous")
    monkeypatch.setattr(tools, "WRITE_ROOTS", ())


def test_the_sealed_folder_is_left_out_of_what_own_code_may_read():
    roots = tools.read_roots()
    config = str(BACKEND_ROOT / "config")
    opened = {str(BACKEND_ROOT.parent / f) for f in tools.UNSEALED}
    assert not any(r == config or (r.startswith(config + "/") and r not in opened) for r in roots)
    assert str(BACKEND_ROOT / "syrax") in roots and "/usr" in roots


@needs_landlock
def test_own_code_cannot_read_the_keys_folder(own_work):
    # a sealed file that is always present (brains.json and the journal sit beside it); config.toml is readable since
    # 2026-10-29 (tools.UNSEALED: app.config loads it, and it holds no key)
    target = BACKEND_ROOT / "config" / "config.syrax.example.toml"
    assert target.exists()
    out = run(f"""
for label, fn in (("open", lambda: open({str(target)!r}).read()),
                  ("shell", lambda: subprocess.run(["cat", {str(target)!r}], capture_output=True, check=True))):
    try:
        fn(); print(label, "READ")
    except Exception as e:
        print(label, "refused")
""")
    # names in the folder may show (import finders list every sys.path folder, and Landlock grants listing by tree);
    # what is in its files does not
    assert "READ" not in out["observation"] and out["observation"].count("refused") == 2, out


@needs_landlock
def test_ordinary_work_still_runs(own_work):
    out = run("""
import json, sqlite3, numpy
import syrax.estop, app.schema  # modules the worker had not loaded: the import finder lists backend
r = subprocess.run(["git", "--version"], capture_output=True, text=True)
p = subprocess.run([sys.executable, "-c", "import json; print('child ok')"], capture_output=True, text=True)
print(open(os.path.join(os.path.dirname(json.__file__), "__init__.py")).read()[:1] != "", r.returncode, p.stdout.strip())
""")
    assert "True 0 child ok" in out["observation"], out


@needs_landlock
def test_config_toml_is_readable_but_nothing_else_in_the_folder(own_work):
    toml, other = BACKEND_ROOT / "config" / "config.toml", BACKEND_ROOT / "config" / "config.example.toml"
    out = run(f"print(len(open({str(toml)!r}).read()) > 0)\ntry:\n    open({str(other)!r}).read(); print('OTHER READ')\n"
              "except PermissionError:\n    print('other refused')")
    assert "True" in out["observation"] and "other refused" in out["observation"], out
