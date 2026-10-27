"""Known-good fallback in the launcher (audit 2026-10-27, item 6): a core that answered /health for
KNOWN_GOOD_SETTLE_S records its commit as known-good; when a core from main then does not come up (it exits, or
/health stays silent for CORE_BOOT_DEADLINE_S), the launcher runs the known-good commit from a worktree of its own
and never resets, checks out or reverts main. The failed commit is marked known-bad so a later start does not try
it again until main moves or a human runs `--restart`.

Nothing here runs git against the real repository: the worktree tests use a repository made in tmp_path."""

import importlib.util
import json
import os
import subprocess
import sys
import time as _time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
X = "b" * 40  # the commit main holds (the new code)
K = "a" * 40  # the known-good commit


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("syrax_launcher_knowngood", ROOT / "syrax.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, value in (("LOG", tmp_path / "syrax.log"), ("PID_FILE", tmp_path / "syrax.pid"), ("_OUTPUT_IS_LOG", False),
                        ("KNOWN_GOOD", tmp_path / "config" / "known_good.json"), ("FALLBACK_TREE", tmp_path / "known-good"),
                        ("BACKEND", tmp_path / "live" / "backend"),
                        ("setup", lambda verbose=False: None), ("check_config", lambda: None),
                        ("port_in_use", lambda port: False), ("ui_is_stale", lambda: False)):
        monkeypatch.setattr(mod, name, value)
    monkeypatch.setattr(sys, "argv", ["syrax.py", "--service"])
    monkeypatch.setenv("SYRAX_OPEN_UI", "0")
    return mod


# ——— the decisions ———

def test_fallback_needs_a_different_known_good_commit(launcher):
    d = launcher.decide_fallback
    assert d(False, None, 0, 5, X, {}) is None  # nothing recorded: the old behaviour
    assert d(False, None, 0, 5, X, {"commit": X}) is None  # the known-good commit is the one that failed
    assert d(False, None, 0, 5, None, {"commit": K}) is None  # no git: no commit to compare
    assert "before it answered /health" in d(False, None, 0, 5, X, {"commit": K})


def test_fallback_when_the_core_dies_or_stays_silent(launcher):
    d, kg = launcher.decide_fallback, {"commit": K}
    dl = launcher.CORE_BOOT_DEADLINE_S
    assert d(True, None, 100, 100 + dl - 1, X, kg) is None  # still has time
    assert f"within {dl} s" in d(True, None, 100, 100 + dl, X, kg)
    assert d(True, 130.0, 100, 100 + dl + 50, X, kg) is None  # it answered: a slow start is not a failure
    assert "before it had run" in d(False, 130.0, 100, 160, X, kg)  # answered, then died before it settled


def test_known_good_is_due_after_the_settle_period(launcher):
    s = launcher.KNOWN_GOOD_SETTLE_S
    assert not launcher.known_good_due(None, 10_000)
    assert not launcher.known_good_due(100, 100 + s - 1)
    assert launcher.known_good_due(100, 100 + s)


def test_known_bad_until_main_moves(launcher):
    kb = launcher.known_bad
    assert kb(X, {"commit": K, "bad": X})
    assert not kb("c" * 40, {"commit": K, "bad": X})  # a newer commit on main is tried
    assert not kb(X, {"commit": K})  # never failed
    assert not kb(X, {"bad": X})  # nothing to fall back to
    assert not kb(X, {"commit": X, "bad": X})


# ——— known_good.json ———

def test_marker_round_trip_atomic(launcher, tmp_path):
    path = launcher.KNOWN_GOOD
    assert launcher.read_known_good() == {}
    launcher.mark_known_good(K, now=1000.0)
    assert json.loads(path.read_text(encoding="utf-8")) == {"commit": K, "at": 1000.0}
    assert not path.with_name(path.name + ".tmp").exists()  # written through a temporary file and a rename
    launcher.mark_bad(X, "the core exited", now=2000.0)
    assert launcher.read_known_good() == {"commit": K, "at": 1000.0, "bad": X, "bad_at": 2000.0, "bad_why": "the core exited"}
    assert launcher.clear_bad() and launcher.read_known_good() == {"commit": K, "at": 1000.0}
    assert not launcher.clear_bad()
    launcher.mark_bad(X, "slow", now=3000.0)
    assert launcher.mark_known_good(X, now=4000.0) == {"commit": X, "at": 4000.0}  # it came up after all: not bad
    path.write_text("{not json", encoding="utf-8")
    assert launcher.read_known_good() == {}


# ——— the worktree ———

def test_worktree_commands(launcher, tmp_path):
    root, tree = tmp_path / "repo", tmp_path / "repo" / ".syrax" / "known-good"
    cmds = launcher.fallback_tree_cmds
    assert cmds(root, tree, K, None) == [["git", "-C", str(root), "worktree", "add", "--force", "--detach", str(tree), K]]
    assert cmds(root, tree, K, X) == [["git", "-C", str(tree), "checkout", "--detach", K]]  # inside the worktree
    assert cmds(root, tree, K, K) == []
    for cmd in cmds(root, tree, K, None) + cmds(root, tree, K, X):
        assert not {"reset", "revert", "stash", "clean"} & set(cmd)


def test_ensure_runs_only_those_commands(launcher, tmp_path):
    root, tree = tmp_path / "repo", tmp_path / "repo" / ".syrax" / "known-good"
    root.mkdir()
    ran = []

    def runner(cmd, **kw):
        ran.append(cmd)
        if cmd[-2:] == ["--show-toplevel", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, f"{tree}\n{K}\n", "")
        if cmd[3:5] == ["worktree", "add"]:
            (tree / ".git").parent.mkdir(parents=True, exist_ok=True)
            (tree / ".git").write_text("gitdir: x")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert launcher.ensure_fallback_tree(K, root=root, tree=tree, runner=runner) == K
    assert ran[0][3:5] == ["worktree", "add"] and ran[1][-2:] == ["--show-toplevel", "HEAD"]
    ran.clear()
    assert launcher.ensure_fallback_tree(K, root=root, tree=tree, runner=runner) == K
    assert len(ran) == 2 and all("checkout" not in c and "add" not in c for c in ran)  # already there: only looked


def test_a_folder_that_is_not_its_own_worktree_is_never_checked_out(launcher, tmp_path):
    """`git -C <plain folder> checkout` would act on the repository above it: the live tree."""
    root, tree = tmp_path / "repo", tmp_path / "repo" / ".syrax" / "known-good"
    (tree / ".git").parent.mkdir(parents=True)
    (tree / ".git").write_text("gitdir: x")
    ran = []

    def runner(cmd, **kw):
        ran.append(cmd)
        if cmd[-2:] == ["--show-toplevel", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 0, f"{root}\n{X}\n", "")  # the toplevel is the repository
        return subprocess.CompletedProcess(cmd, 1, "", "fatal: already exists")

    assert launcher.ensure_fallback_tree(K, root=root, tree=tree, runner=runner) is None
    assert not any("checkout" in c for c in ran)
    assert launcher.ensure_fallback_tree(K, root=root, tree=root, runner=runner) is None  # never the repository itself


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def test_a_real_worktree_leaves_main_and_its_tree_alone(launcher, tmp_path, monkeypatch):
    for k in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CEILING_DIRECTORIES", "GIT_NAMESPACE"):
        monkeypatch.delenv(k, raising=False)  # a hook's GIT_DIR would send every git call below to the real repository
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("one\n")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-q", "-m", "one")
    k1 = git(repo, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("two\n")
    git(repo, "commit", "-q", "-am", "two")
    k2 = git(repo, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("three\n")
    git(repo, "commit", "-q", "-am", "three")
    head = git(repo, "rev-parse", "HEAD")
    (repo / "wip.txt").write_text("the human's uncommitted work\n")
    tree = repo / ".syrax" / "known-good"

    assert launcher.ensure_fallback_tree(k1, root=repo, tree=tree) == k1
    assert (tree / "f.txt").read_text() == "one\n"
    assert launcher.ensure_fallback_tree(k2, root=repo, tree=tree) == k2  # reused, moved inside the worktree
    assert (tree / "f.txt").read_text() == "two\n"
    assert git(repo, "rev-parse", "HEAD") == head and git(repo, "rev-parse", "--abbrev-ref", "HEAD") != "HEAD"
    assert (repo / "f.txt").read_text() == "three\n" and (repo / "wip.txt").exists()
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""


# ——— the fallback core's environment and files ———

def test_fallback_env_points_at_the_live_files_and_turns_self_work_off(launcher, tmp_path):
    live = tmp_path / "live" / "backend"
    env = launcher.fallback_env({"PATH": "p", "SYRAX_MEMORY_FILE": "/mine.json", "SYRAX_AUTONOMY": "1"}, live, K)
    assert env["SYRAX_JOURNAL_FILE"] == str(live / "config" / "journal.db")
    assert env["SYRAX_BRAINS_FILE"] == str(live / "config" / "brains.json")
    assert env["SYRAX_TOKEN_FILE"] == str(live / "config" / "ws.token")
    assert env["SYRAX_SKILLS_DIR"] == str(live / "skills")
    assert env["SYRAX_MEMORY_FILE"] == "/mine.json"  # an explicit setting stays
    assert all(env[k] == "0" for k in ("SYRAX_AUTONOMY", "SYRAX_SELF_RESTART", "SYRAX_ISOLATE", "SYRAX_PUBLISH_RISE"))
    assert env["SYRAX_FALLBACK"] == K and env["PATH"] == "p"


def test_config_is_hard_linked_never_copied(launcher, tmp_path):
    live, tree = tmp_path / "live" / "backend", tmp_path / "known-good" / "backend"
    (live / "config").mkdir(parents=True)
    (live / "config" / "config.toml").write_text("[llm]\nkey = 'live'\n")
    (tree / "config").mkdir(parents=True)
    (tree / "config" / "config.toml").write_text("stale\n")
    assert launcher.link_live_files(tree, live) == ["config.toml"]  # mcp.json is absent: skipped
    assert os.path.samefile(live / "config" / "config.toml", tree / "config" / "config.toml")
    assert (live / "config" / "config.toml").read_text() == "[llm]\nkey = 'live'\n"  # the live file is untouched
    assert launcher.link_live_files(tree, live) == ["config.toml"]  # again: already the same file
    assert launcher.link_live_files(live, live) == []


# ——— launch(): the loop ———

class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture
def world(launcher, monkeypatch, tmp_path):
    """launch() with fake processes, a fake clock and /health answering when the test says so."""
    for k in ("SYRAX_JOURNAL_FILE", "SYRAX_TOKEN_FILE", "SYRAX_BRAINS_FILE", "SYRAX_MEMORY_FILE", "SYRAX_HISTORY_FILE"):
        monkeypatch.delenv(k, raising=False)  # the test session points them at its own files; a service has none set
    clock = Clock()
    w = types.SimpleNamespace(started=[], answers=lambda: False, journaled=[], trees=[], clock=clock, core_dies_at=None)

    class Fake:
        def __init__(self, name, cmd, cwd, log, env=None):
            self.name, self.cwd, self.env, self.born = name, Path(cwd), env, clock.t
            self.proc = types.SimpleNamespace(returncode=1)
            self.stopped = False
            w.started.append(self)

        def alive(self):
            if self.stopped:
                return False
            if self.name == "core" and w.core_dies_at is not None:
                return clock.t - self.born < w.core_dies_at(self)
            return True

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(launcher, "time", types.SimpleNamespace(time=clock.time, sleep=clock.sleep, strftime=_time.strftime))
    monkeypatch.setattr(launcher, "Component", Fake)
    monkeypatch.setattr(launcher, "head_commit", lambda root=None: X)
    monkeypatch.setattr(launcher, "syrax_answers", lambda: w.answers())
    monkeypatch.setattr(launcher, "ensure_fallback_tree", lambda commit, **kw: (w.trees.append(commit), commit)[1])
    monkeypatch.setattr(launcher, "link_live_files", lambda backend, live=None: [])
    monkeypatch.setattr(launcher, "journal_fallback", lambda backend, env, bad, good, why: w.journaled.append((bad, good, why)) or True)
    return w


def cores(w):
    return [c for c in w.started if c.name == "core"]


def test_a_core_that_never_answers_falls_back(launcher, world):
    launcher.mark_known_good(K, now=1.0)
    world.core_dies_at = lambda c: 10**9 if c.cwd == launcher.BACKEND else 30  # the fallback ends the run later
    assert launcher.launch(dev=False, service=True, watch=True) == 0
    main_core, fb = cores(world)
    assert main_core.cwd == launcher.BACKEND and main_core.stopped
    assert fb.cwd == launcher.FALLBACK_TREE / "backend" and fb.env["SYRAX_AUTONOMY"] == "0"
    assert fb.env["SYRAX_JOURNAL_FILE"] == str(launcher.BACKEND / "config" / "journal.db")
    assert world.trees == [K] and world.journaled and world.journaled[0][:2] == (X, K)
    assert f"within {launcher.CORE_BOOT_DEADLINE_S} s" in world.journaled[0][2]
    kg = launcher.read_known_good()
    assert kg["commit"] == K and kg["bad"] == X
    log = launcher.LOG.read_text(encoding="utf-8")
    assert "falling back to the known-good commit" in log and "main and the working tree are not touched" in log


def test_a_core_that_crashes_falls_back(launcher, world):
    launcher.mark_known_good(K, now=1.0)
    world.core_dies_at = lambda c: 5 if c.cwd == launcher.BACKEND else 40
    assert launcher.launch(dev=False, service=True, watch=True) == 0
    assert [c.cwd for c in cores(world)] == [launcher.BACKEND, launcher.FALLBACK_TREE / "backend"]
    assert "before it answered /health" in launcher.read_known_good()["bad_why"]


def test_a_core_that_answers_becomes_known_good(launcher, world):
    launcher.mark_known_good(K, now=1.0)
    world.answers = lambda: True
    world.core_dies_at = lambda c: launcher.KNOWN_GOOD_SETTLE_S + 30  # well after it settled: today's shutdown
    assert launcher.launch(dev=False, service=True, watch=True) == 0
    assert len(cores(world)) == 1 and world.trees == [] and world.journaled == []
    kg = launcher.read_known_good()
    assert kg["commit"] == X and "bad" not in kg
    assert "core exited (code 1), shutting down" in launcher.LOG.read_text(encoding="utf-8")


def test_a_known_bad_commit_is_not_tried_again(launcher, world):
    launcher.mark_known_good(K, now=1.0)
    launcher.mark_bad(X, "the core exited 3 s after it started", now=2.0)
    world.core_dies_at = lambda c: 50
    assert launcher.launch(dev=False, service=True, watch=True) == 0
    assert [c.cwd for c in cores(world)] == [launcher.FALLBACK_TREE / "backend"]  # main was not started
    assert launcher.read_known_good()["bad_why"] == "the core exited 3 s after it started"  # the first reason stays


def test_once_main_moves_it_is_tried(launcher, world, monkeypatch):
    launcher.mark_known_good(K, now=1.0)
    launcher.mark_bad("c" * 40, "older failure", now=2.0)
    world.answers = lambda: True
    world.core_dies_at = lambda c: launcher.KNOWN_GOOD_SETTLE_S + 30
    assert launcher.launch(dev=False, service=True, watch=True) == 0
    assert [c.cwd for c in cores(world)] == [launcher.BACKEND]
    assert launcher.read_known_good()["commit"] == X


def test_a_failing_fallback_core_is_not_followed_by_another(launcher, world):
    launcher.mark_known_good(K, now=1.0)
    world.core_dies_at = lambda c: 5
    assert launcher.launch(dev=False, service=True, watch=True) == 0
    assert len(cores(world)) == 2  # main, then the fallback once; then the old shutdown
    assert "core exited (code 1), shutting down" in launcher.LOG.read_text(encoding="utf-8")


def test_without_watch_or_outside_the_service_nothing_falls_back(launcher, world):
    launcher.mark_known_good(K, now=1.0)
    world.core_dies_at = lambda c: 5
    assert launcher.launch(dev=False, service=True) == 0  # launch() called directly: the old behaviour
    assert launcher.launch(dev=False, service=False, watch=True) == 0  # a foreground start: the human sees it
    assert len(cores(world)) == 2 and world.trees == [] and "bad" not in launcher.read_known_good()


def test_no_fallback_when_the_worktree_cannot_be_made(launcher, world, monkeypatch):
    launcher.mark_known_good(K, now=1.0)
    monkeypatch.setattr(launcher, "ensure_fallback_tree", lambda commit, **kw: None)
    world.core_dies_at = lambda c: 5
    assert launcher.launch(dev=False, service=True, watch=True) == 0
    assert len(cores(world)) == 1 and "bad" not in launcher.read_known_good()
    assert "could not be prepared" in launcher.LOG.read_text(encoding="utf-8")


# ——— main(): who restarts ———

def test_a_human_restart_clears_the_mark_and_syraxs_own_does_not(launcher, monkeypatch):
    monkeypatch.setattr(launcher, "stop", lambda: 0)
    monkeypatch.setattr(launcher, "start_detached", lambda: 0)
    launcher.mark_known_good(K, now=1.0)
    launcher.mark_bad(X, "x", now=2.0)
    assert launcher.main(["--restart", "--self-restart"]) == 0
    assert launcher.read_known_good()["bad"] == X
    assert launcher.main(["--restart"]) == 0
    assert "bad" not in launcher.read_known_good()


def test_respawn_starts_a_self_restart(launcher, monkeypatch):
    seen = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda cmd, **kw: seen.append(cmd))
    assert launcher.main(["--respawn"]) == 0
    assert seen and seen[0][-2:] == ["--restart", "--self-restart"]


def test_journal_fallback_runs_the_known_good_code_against_the_given_journal(launcher, tmp_path, monkeypatch):
    """The real subprocess: `python -m syrax.knowngood` from a backend folder, the journal named by the environment."""
    monkeypatch.setattr(launcher, "VENV", Path(sys.executable).resolve().parents[1])  # this venv runs the test
    db = tmp_path / "journal.db"
    env = {**os.environ, "SYRAX_JOURNAL_FILE": str(db)}
    assert launcher.journal_fallback(ROOT / "backend", env, X, K, "the core exited 3 s after it started")
    from syrax.journal import Journal

    j = Journal(db, recover=False)
    try:
        (ev,) = j.events_of_type("restart.fallback", limit=5)
        assert ev["payload"] == {"from": X, "to": K, "why": "the core exited 3 s after it started"}
        assert j.events_of_type("reminder.created", limit=5)
    finally:
        j.close()
