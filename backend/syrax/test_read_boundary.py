"""2026-10-29: the kernel boundary around SYRAX's own code limited writes only, so its python_execute could still read
backend/config: the brain keys (brains.json), the journal and the UI token. Now own work reads only the system, the
interpreter and venv, harmless git config and the repository except backend/config; ordinary work still runs."""

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
    assert not any(r == config or r.startswith(config + "/") for r in roots)
    assert str(BACKEND_ROOT / "syrax") in roots and "/usr" in roots


@needs_landlock
def test_own_code_cannot_read_the_keys_folder(own_work):
    target = BACKEND_ROOT / "config" / "config.toml"  # always present; brains.json and the journal sit beside it
    assert target.exists()
    out = run(f"""
for label, fn in (("open", lambda: open({str(target)!r}).read()),
                  ("listdir", lambda: os.listdir({str(target.parent)!r})),
                  ("shell", lambda: subprocess.run(["cat", {str(target)!r}], capture_output=True, check=True))):
    try:
        fn(); print(label, "READ")
    except Exception as e:
        print(label, "refused")
""")
    assert "READ" not in out["observation"] and out["observation"].count("refused") == 3, out


@needs_landlock
def test_ordinary_work_still_runs(own_work):
    out = run("""
import json, sqlite3, numpy
r = subprocess.run(["git", "--version"], capture_output=True, text=True)
p = subprocess.run([sys.executable, "-c", "import json; print('child ok')"], capture_output=True, text=True)
print(open(os.path.join(os.path.dirname(json.__file__), "__init__.py")).read()[:1] != "", r.returncode, p.stdout.strip())
""")
    assert "True 0 child ok" in out["observation"], out
