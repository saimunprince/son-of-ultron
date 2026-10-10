"""M1, isolated evolution: an autonomous task edits, gates and commits in its
own worktree; the running tree changes only by a fast-forward of a released
commit; an unreleased attempt is kept as a diff and its worktree removed.
Throwaway git repositories and fake gates only."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from syrax.devloop import DevLoop, remove_worktree
from syrax.journal import Journal
from syrax.verify import Gate

PASS = [Gate("ok", [sys.executable, "-c", "pass"])]
FAIL = [Gate("tests", [sys.executable, "-c", "import sys; sys.exit(1)"])]
PLAN = {"why": "objective", "risk": "mod callers", "tests": "test_new.py"}


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def repo(tmp_path):
    root = tmp_path / "live"
    (root / "backend" / "syrax").mkdir(parents=True)
    (root / "backend" / "config").mkdir()
    git(root, "init", "-q")
    (root / ".gitignore").write_text(".syrax/\nbackend/config/config.toml\n")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 1\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    (root / "backend" / "config" / "config.toml").write_text("[llm]\n")  # untracked, needed to import
    return root


def isolated(tmp_path, gates=PASS, kind="autonomous"):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] improve mod", kind=kind)
    dl = DevLoop(j, root=root, gates=lambda: gates, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    dl.begin_task()
    wt = dl.isolate(t)
    return root, j, t, dl, wt


def test_isolate_gives_the_task_its_own_checkout(tmp_path):
    root, j, t, dl, wt = isolated(tmp_path)
    assert wt == root / ".syrax" / "worktrees" / t and wt.is_dir()
    assert dl.root == wt and dl.live_root == root and dl.isolated == wt
    assert (wt / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"
    assert (wt / "backend" / "config" / "config.toml").exists()  # copied: a checkout has no untracked files
    assert git(root, "status", "--porcelain") == ""  # the worktree is ignored by the running tree


def test_a_released_change_lands_in_the_running_tree_only_by_fast_forward(tmp_path):
    root, j, t, dl, wt = isolated(tmp_path)
    head0 = git(root, "rev-parse", "HEAD")
    (wt / "backend" / "syrax" / "mod.py").write_text("VALUE = 2\n")
    (wt / "backend" / "syrax" / "test_new.py").write_text("def test_n(): assert True\n")
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"  # the running tree is untouched while it works
    rep = asyncio.run(dl.release("bump VALUE", PLAN))
    assert rep["outcome"] == "COMMITTED"
    assert git(root, "rev-parse", "HEAD") == rep["commit"] != head0
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 2\n"
    assert git(root, "status", "--porcelain") == ""


def test_a_failed_change_never_reaches_the_running_tree(tmp_path):
    root, j, t, dl, wt = isolated(tmp_path, gates=FAIL)
    head0 = git(root, "rev-parse", "HEAD")
    (wt / "backend" / "syrax" / "mod.py").write_text("VALUE = 3\n")
    rep = asyncio.run(dl.release("break it", PLAN))
    assert rep["outcome"] == "ROLLED_BACK"
    assert git(root, "rev-parse", "HEAD") == head0 and (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"


def test_nothing_lands_when_the_running_tree_moved(tmp_path):
    root, j, t, dl, wt = isolated(tmp_path)
    (root / "README.md").write_text("a human commit meanwhile\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "human")
    human = git(root, "rev-parse", "HEAD")
    (wt / "backend" / "syrax" / "mod.py").write_text("VALUE = 4\n")
    rep = asyncio.run(dl.release("bump", PLAN))
    assert rep["outcome"] == "COMMIT_FAILED" and "could not fast-forward the running tree" in rep["error"]
    assert git(root, "rev-parse", "HEAD") == human and (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"
    assert not [e for e in j.events(t) if e["type"] == "commit.created"]  # no commit is claimed


def test_discard_restores_the_running_trees_baseline_and_removes_the_worktree(tmp_path):
    root = repo(tmp_path)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 99  # a human's uncommitted work\n")
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("x", kind="autonomous")
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    dl.begin_task()
    assert "backend/syrax/mod.py" in dl.baseline
    wt = dl.isolate(t)
    assert dl.baseline == {}
    dl.discard()
    assert not wt.exists() and dl.root == root and dl.isolated is None
    assert "backend/syrax/mod.py" in dl.baseline  # the human's work stays protected from the task's cleanup
    assert (root / "backend" / "syrax" / "mod.py").read_text().startswith("VALUE = 99")


def test_removing_a_worktree_never_follows_a_leftover_modules_link(tmp_path):
    root, j, t, dl, wt = isolated(tmp_path)
    shared = tmp_path / "shared_node_modules"
    (shared / "pkg").mkdir(parents=True)
    (shared / "pkg" / "index.js").write_text("1\n")
    (wt / "frontend").mkdir()
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(shared), str(wt / "frontend" / "node_modules"))
    else:
        os.symlink(shared, wt / "frontend" / "node_modules", target_is_directory=True)
    remove_worktree(wt, root)
    assert not wt.exists()
    assert (shared / "pkg" / "index.js").read_text() == "1\n"  # the shared modules survive


def test_leftover_worktrees_are_pruned_when_the_next_task_isolates(tmp_path):
    root, j, t, dl, wt = isolated(tmp_path)
    dl.isolated = None  # as after a crash: nobody owns it any more
    dl.root = root
    t2 = j.start_task_sync("next", kind="autonomous")
    wt2 = dl.isolate(t2)
    assert not wt.exists() and wt2.is_dir()


def test_the_core_keeps_an_unreleased_worktree_diff_and_removes_the_worktree(tmp_path):
    from syrax.core import Core, Running

    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    c = Core(j)
    c.devloop = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: None, snapshot_dir=tmp_path / "rb")
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] x", kind="autonomous")
    c.devloop.begin_task()
    wt = c.devloop.isolate(t)
    (wt / "backend" / "syrax" / "mod.py").write_text("VALUE = 5\n")
    c.current = Running(task_id=t, goal="x", session_id=None, kind="autonomous")
    c.current.steps.append({"step": 1, "tool": "python_execute", "id": "a", "ok": True})
    asyncio.run(c._clean_repo_after_task())
    rb = [e for e in j.events(t) if e["type"] == "rollback.created"][0]["payload"]
    assert rb["worktree"] == str(wt) and "backend/syrax/mod.py" in rb["files"] and rb["removed"] == ["backend/syrax/mod.py"]
    assert "VALUE = 5" in Path(rb["snapshot"]).read_text()  # the next attempt can re-apply it
    assert not wt.exists() and c.devloop.isolated is None
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"  # the running tree never changed


def test_submit_isolates_autonomous_work_only_when_the_service_asks(tmp_path, monkeypatch):
    from syrax.core import Core

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
            return "done"

    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    c = Core(j)
    c.devloop = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: None, snapshot_dir=tmp_path / "rb")

    async def build():
        return Agent()

    c._build_agent = build
    seen = {}

    async def go(kind):
        tid = await c.submit("work", None, None, kind=kind)
        seen[kind] = c.devloop.isolated
        await c.wait()
        return tid

    monkeypatch.setenv("SYRAX_ISOLATE", "1")
    t = asyncio.run(go("autonomous"))
    assert seen["autonomous"] == root / ".syrax" / "worktrees" / t
    assert [e["type"] for e in j.events(t)][1] == "isolation.started"
    assert c.devloop.isolated is None and not (root / ".syrax" / "worktrees" / t).exists()  # closed with the task
    asyncio.run(go("conversation"))
    assert seen["conversation"] is None  # a human's conversation never gets a worktree
    monkeypatch.setenv("SYRAX_ISOLATE", "0")
    asyncio.run(go("autonomous"))
    assert seen["autonomous"] is None  # off unless the service turns it on
