"""Audit 2026-10-28: SYRAX's own work could write .git/hooks/pre-commit through the editor (allowed in every task
kind), and the server's next `git commit` for a release ran the hook outside every guard and boundary. Own code may
also write its worktree's `.git` link (Landlock grants the worktree) and lend git a config of its making.

Now own work may not write git's files, every git the server starts runs with hooks and fsmonitor off, and a
worktree's link must still say what git wrote."""

import os
import subprocess

import pytest

from syrax import devloop, permissions as P


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git("init", "-q", cwd=r)
    git("config", "user.email", "t@t", cwd=r)
    git("config", "user.name", "t", cwd=r)
    (r / "a.txt").write_text("a")
    git("add", "a.txt", cwd=r)
    git("-c", "core.hooksPath=", "commit", "-q", "-m", "a", cwd=r)
    return r


@pytest.mark.parametrize("kind", ["autonomous", "eval"])
@pytest.mark.parametrize("rel", [".git/hooks/pre-commit", ".git/config", ".git"])
def test_own_work_may_not_write_git_s_files(repo, kind, rel):
    d = P.classify("str_replace_editor", {"command": "create", "path": str(repo / rel), "file_text": "x"})
    v = P.decide(d, kind, "")
    assert v.action == "refuse" and "git's own files" in v.reason


def test_the_server_s_git_runs_no_hooks(repo, tmp_path):
    marker = tmp_path / "hook-ran"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    git("config", "core.fsmonitor", f"sh -c 'touch {marker}' #", cwd=repo)
    (repo / "b.txt").write_text("b")
    assert devloop._git(["add", "b.txt"], repo).returncode == 0
    assert devloop._git(["status", "--porcelain"], repo).returncode == 0
    r = devloop._git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "b"], repo)
    assert r.returncode == 0, r.stderr
    assert not marker.exists()  # neither the hook nor the fsmonitor command ran


def test_a_rewritten_worktree_link_stops_git(repo, tmp_path):
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", "--detach", str(wt), "HEAD", cwd=repo)
    devloop.remember_worktree_link(wt)
    assert devloop._git(["status", "--porcelain"], wt).returncode == 0
    fake = wt / "fake" / ".git" / "worktrees" / "x"
    fake.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {fake}\n")  # own code lends git a config of its making
    with pytest.raises(RuntimeError, match="changed after git made it"):
        devloop._git(["status"], wt)
    devloop.WORKTREE_LINKS.pop(str(wt.resolve()), None)  # unknown worktree: the structural check still refuses
    with pytest.raises(RuntimeError, match="does not point at a repository"):
        devloop._git(["status"], wt)


def test_safe_env_keeps_existing_injected_config():
    env = devloop.git_safe_env({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": "*"})
    assert env["GIT_CONFIG_COUNT"] == "3" and env["GIT_CONFIG_KEY_0"] == "safe.directory"
    assert {env["GIT_CONFIG_KEY_1"], env["GIT_CONFIG_KEY_2"]} == {"core.hooksPath", "core.fsmonitor"}
