"""M1's last gap: while a task works in its own worktree, code it runs with
python_execute cannot write the running tree either, directly or from a
Python it starts; the worktree and the workspace stay writable."""

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax import editor as ed  # noqa: E402
from syrax import guard  # noqa: E402
from syrax.tools import AsyncPythonExecute  # noqa: E402


def run_tool(code: str) -> dict:
    return asyncio.new_event_loop().run_until_complete(AsyncPythonExecute().execute(code=code, timeout=60))


def tree(tmp_path):
    live = tmp_path / "live"
    wt = live / ".syrax" / "worktrees" / "t1"
    for base in (live, wt):
        (base / "backend" / "syrax").mkdir(parents=True)
        (base / "backend" / "syrax" / "mod.py").write_text("VALUE = 1\n")
    (live / "backend" / "workspace").mkdir()
    return live, wt


def test_no_rules_without_an_isolated_task(monkeypatch):
    monkeypatch.setattr(ed, "ROOT_MAP", None)
    assert guard.isolation_rules() == [] and not any(p.endswith("*") for p in guard.protected_paths())


def test_isolated_python_cannot_write_the_running_tree(tmp_path, monkeypatch):
    live, wt = tree(tmp_path)
    monkeypatch.setattr(ed, "ROOT_MAP", (live, wt))
    target = live / "backend" / "syrax" / "mod.py"
    out = run_tool(f"open(r'{target}', 'w').write('VALUE = 99')")
    assert out["success"] is False and "read-only while this task works in its own worktree" in out["observation"]
    assert target.read_text() == "VALUE = 1\n"
    out = run_tool(f"import os\nos.remove(r'{target}')")
    assert out["success"] is False and target.exists()
    out = run_tool(f"print(open(r'{target}').read().strip())")  # reading stays allowed
    assert out == {"observation": "VALUE = 1\n", "success": True}


def test_the_worktree_and_the_workspace_stay_writable(tmp_path, monkeypatch):
    live, wt = tree(tmp_path)
    monkeypatch.setattr(ed, "ROOT_MAP", (live, wt))
    out = run_tool(f"open(r'{wt / 'backend' / 'syrax' / 'mod.py'}', 'w').write('VALUE = 2')\n"
                   f"open(r'{live / 'backend' / 'workspace' / 'out.txt'}', 'w').write('x')\nprint('ok')")
    assert out == {"observation": "ok\n", "success": True}
    assert (wt / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 2"


def test_a_python_it_starts_is_held_to_the_same_rule(tmp_path, monkeypatch):
    live, wt = tree(tmp_path)
    monkeypatch.setattr(ed, "ROOT_MAP", (live, wt))
    target = live / "backend" / "syrax" / "mod.py"
    child = f"open(r'{target}', 'w').write('VALUE = 7')"
    code = ("import subprocess, sys\n"
            f"r = subprocess.run([sys.executable, '-c', {child!r}], capture_output=True, text=True)\n"
            "print('child exit', r.returncode, 'read-only' in r.stderr)")
    out = run_tool(code)
    assert out["success"] and "child exit 1 True" in out["observation"]
    assert target.read_text() == "VALUE = 1\n"
