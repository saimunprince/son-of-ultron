"""M1 step 3: while a task is isolated, the editor writes into its worktree,
its edits are recorded as isolated, and the ledger counts any own edit that
still lands in the running tree."""

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

from syrax import editor as ed
from syrax import rise
from syrax.core import _repo_edit
from syrax.editor import SyraxEditor
from syrax.journal import Journal

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def mapped(tmp_path, monkeypatch):
    live, wt = tmp_path / "live", tmp_path / "live" / ".syrax" / "worktrees" / "t1"
    for base in (live, wt):
        (base / "backend" / "syrax").mkdir(parents=True)
        (base / "backend" / "syrax" / "mod.py").write_text("VALUE = 1\n")
    (live / "backend" / "workspace").mkdir(parents=True)
    monkeypatch.setattr(ed, "ROOT_MAP", (live, wt))
    return live, wt


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_edits_to_running_tree_paths_land_in_the_worktree(mapped):
    live, wt = mapped
    tool = SyraxEditor()
    tool._file_history.clear()
    run(tool.execute(command="str_replace", path=str(live / "backend" / "syrax" / "mod.py"), old_str="VALUE = 1", new_str="VALUE = 2"))
    assert (wt / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 2\n"
    assert (live / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"  # the running tree is untouched
    out = run(tool.execute(command="view", path=str(live / "backend" / "syrax" / "mod.py")))
    assert "VALUE = 2" in out  # it reads its own change back
    run(tool.execute(command="create", path=str(live / "backend" / "syrax" / "new.py"), file_text="X = 1\n"))
    assert (wt / "backend" / "syrax" / "new.py").exists() and not (live / "backend" / "syrax" / "new.py").exists()


def test_the_workspace_config_and_worktree_paths_are_not_redirected(mapped):
    live, wt = mapped
    assert ed.redirect(live / "backend" / "workspace" / "out.txt") == live / "backend" / "workspace" / "out.txt"
    assert ed.redirect(live / "backend" / "config" / "brains.json") == live / "backend" / "config" / "brains.json"
    assert ed.redirect(wt / "backend" / "syrax" / "mod.py") == wt / "backend" / "syrax" / "mod.py"
    assert ed.redirect(Path("C:/elsewhere/file.txt") if sys.platform == "win32" else Path("/elsewhere/file.txt")).name == "file.txt"


def test_an_isolated_edit_is_recorded_relative_to_the_worktree(mapped):
    live, wt = mapped
    edit = _repo_edit([{"step": 3}], {"command": "str_replace", "path": str(live / "backend" / "syrax" / "mod.py")})
    assert edit == {"path": str(Path("backend/syrax/mod.py")), "command": "str_replace", "step": 3, "isolated": True}
    edit = _repo_edit([{"step": 4}], {"command": "create", "path": str(wt / "backend" / "syrax" / "x.py")})
    assert edit["isolated"] is True and edit["path"] == str(Path("backend/syrax/x.py"))


def test_the_ledger_counts_own_edits_in_the_running_tree(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("own work", kind="autonomous")
    j.record_sync("code.changed", {"path": "backend/syrax/a.py", "command": "str_replace", "step": 1}, task_id=t)
    j.record_sync("code.changed", {"path": "backend/syrax/b.py", "command": "str_replace", "step": 2, "isolated": True}, task_id=t)
    h = j.start_task_sync("a human edit", kind="conversation")
    j.record_sync("code.changed", {"path": "backend/syrax/c.py", "command": "create", "step": 1}, task_id=h)
    j.close()
    m = {r["id"]: r for r in rise.measure(tmp_path / "j.db", time.time() + 1)["metrics"]}  # + 1: the window ends before `now`, and time.time() ticks every 15.6 ms on Windows
    assert m["live_tree_edits"]["last"]["value"] == 1 and m["live_tree_edits"]["better"] == "lower"


def test_the_service_launcher_turns_isolation_on(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("syrax_launcher_iso", ROOT / "syrax.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, value in (("LOG", tmp_path / "syrax.log"), ("PID_FILE", tmp_path / "syrax.pid"), ("_OUTPUT_IS_LOG", False),
                        ("setup", lambda verbose=False: None), ("check_config", lambda: None),
                        ("port_in_use", lambda port: False), ("ui_is_stale", lambda: False)):
        monkeypatch.setattr(mod, name, value)
    # setenv first so monkeypatch remembers the variable's original state: launch() sets it
    # with setdefault, and a bare delenv of an absent variable would let that leak into later tests
    monkeypatch.setenv("SYRAX_ISOLATE", "placeholder")
    monkeypatch.delenv("SYRAX_ISOLATE")
    monkeypatch.setenv("SYRAX_OPEN_UI", "0")
    seen = []

    class Fake:
        def __init__(self, name, cmd, cwd, log):
            self.name, self.proc = name, type("P", (), {"returncode": 0})()
            seen.append(__import__("os").environ.get("SYRAX_ISOLATE"))

        def alive(self):
            return False if self.name == "core" else True

        def stop(self):
            pass

    monkeypatch.setattr(mod, "Component", Fake)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    assert mod.launch(dev=False, service=True) == 0
    assert seen[0] == "1"


def test_the_core_maps_paths_and_tells_the_brief_only_during_the_isolated_task(tmp_path, monkeypatch):
    import subprocess

    from syrax.core import Core
    from syrax.devloop import DevLoop
    from syrax.verify import Gate

    root = tmp_path / "live"
    (root / "backend" / "syrax").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".gitignore").write_text(".syrax/\n")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"], cwd=root, check=True)
    seen = {}

    class Agent:
        step_limit_hit = False
        loop_stopped = False

        def reset_conversation(self):
            pass

        def repair_memory(self, aborted=False):
            pass

        def export_context(self):
            return []

        def import_context(self, ctx):
            return 0

        async def run(self, request):
            seen["map"], seen["request"] = ed.ROOT_MAP, request
            return "done"

    j = Journal(tmp_path / "j.db")
    c = Core(j)
    c.devloop = DevLoop(j, root=root, gates=lambda: [Gate("ok", [sys.executable, "-c", "pass"])], snapshot_dir=tmp_path / "rb")

    async def build():
        return Agent()

    c._build_agent = build
    monkeypatch.setenv("SYRAX_ISOLATE", "1")

    async def go():
        tid = await c.submit("[AUTONOMOUS OBJECTIVE] work", None, None, kind="autonomous")
        await c.wait()
        return tid

    t = asyncio.run(go())
    assert seen["map"] == (root, root / ".syrax" / "worktrees" / t)
    assert "[ISOLATED WORKTREE]" in seen["request"] and str(root / ".syrax" / "worktrees" / t) in seen["request"]
    assert ed.ROOT_MAP is None  # cleared with the task: nothing keeps writing into a removed copy
