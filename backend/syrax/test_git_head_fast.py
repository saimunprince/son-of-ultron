"""journal._git_head reads HEAD from the repository files and must always agree with git."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from syrax import journal

REPO_ROOT = Path(__file__).resolve().parents[2]


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                          cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def real_head(cwd):
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(cwd), capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def commit(root, name, text):
    (root / name).write_text(text)
    git(root, "add", name)
    git(root, "commit", "-q", "-m", name)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    commit(root, "a.txt", "1")
    commit(root, "b.txt", "2")
    return root


@pytest.fixture
def spy(monkeypatch):
    """Counts the times _git_head falls back to running git."""
    calls = []
    real_run = subprocess.run

    def run(cmd, *a, **kw):
        calls.append(cmd)
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(journal, "subprocess", SimpleNamespace(run=run))
    return calls


def fast(cwd):
    return journal._git_head_from_files(Path(cwd))


def test_branch_head_is_read_from_the_loose_ref(repo, spy):
    assert fast(repo) == real_head(repo)
    assert journal._git_head(repo) == real_head(repo) and not spy


def test_subdirectory_walks_up_to_the_repo(repo):
    sub = repo / "x" / "y"
    sub.mkdir(parents=True)
    assert fast(sub) == real_head(sub) == real_head(repo)


def test_other_branch_and_detached_head(repo):
    git(repo, "checkout", "-q", "-b", "feature/one")
    commit(repo, "c.txt", "3")
    assert fast(repo) == real_head(repo)
    git(repo, "checkout", "-q", "--detach", "HEAD~1")
    assert (repo / ".git" / "HEAD").read_text().strip() == real_head(repo)
    assert fast(repo) == real_head(repo)


def test_packed_refs(repo, spy):
    git(repo, "checkout", "-q", "-b", "side")
    commit(repo, "d.txt", "4")
    git(repo, "tag", "-a", "v1", "-m", "v1")  # a peeled line in packed-refs
    git(repo, "pack-refs", "--all")
    assert not (repo / ".git" / "refs" / "heads" / "side").exists()
    assert "^" in (repo / ".git" / "packed-refs").read_text()
    assert fast(repo) == real_head(repo)
    assert journal._git_head(repo) == real_head(repo) and not spy


def test_worktree_reads_its_own_head_and_the_common_refs(repo, tmp_path, spy):
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "wtb", str(wt))
    commit(wt, "e.txt", "5")
    assert (wt / ".git").is_file()
    assert fast(wt) == real_head(wt) != real_head(repo)
    assert fast(repo) == real_head(repo)
    git(repo, "pack-refs", "--all")
    assert fast(wt) == real_head(wt)
    git(wt, "checkout", "-q", "--detach", "HEAD~1")
    assert fast(wt) == real_head(wt)
    assert journal._git_head(wt) == real_head(wt) and not spy


def test_non_repo_is_none(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    if real_head(plain) is not None:
        pytest.skip("the temp dir lives inside a git repository")
    assert fast(plain) is None and journal._git_head(plain) is None


def test_live_repo_matches_git():
    assert fast(REPO_ROOT) == real_head(REPO_ROOT)
    assert journal._git_head(REPO_ROOT) == real_head(REPO_ROOT)


@pytest.mark.parametrize("head", [
    "ref: refs/heads/../../evil\n",
    "ref: refs/remotes/origin/main\n",   # not a branch: let git answer
    "0123\n",                             # truncated sha
    "ref: refs/heads/main\r\n",
    "garbage\n",
])
def test_odd_head_falls_back_to_git(repo, spy, head):
    (repo / ".git" / "HEAD").write_text(head, newline="")
    assert fast(repo) is journal._FALLBACK
    assert journal._git_head(repo) == real_head(repo)
    assert spy and spy[0][:3] == ["git", "rev-parse", "HEAD"]


def test_symbolic_ref_chain_falls_back(repo, spy):
    git(repo, "symbolic-ref", "refs/heads/alias", "refs/heads/main")
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/alias\n", newline="")
    assert fast(repo) is journal._FALLBACK
    assert journal._git_head(repo) == real_head(repo) and spy


def test_corrupt_loose_ref_and_unborn_branch_fall_back(repo, tmp_path, spy):
    (repo / ".git" / "refs" / "heads" / "main").write_text("not a sha\n")
    assert fast(repo) is journal._FALLBACK
    assert journal._git_head(repo) == real_head(repo) and spy
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    git(fresh, "init", "-q", "-b", "main")
    assert fast(fresh) is journal._FALLBACK
    assert journal._git_head(fresh) is None and real_head(fresh) is None


def test_bad_gitdir_file_and_env_fall_back(repo, tmp_path, monkeypatch):
    odd = tmp_path / "odd"
    odd.mkdir()
    (odd / ".git").write_text("nonsense\n")
    assert fast(odd) is journal._FALLBACK
    (odd / ".git").write_text("gitdir: " + str(tmp_path / "missing") + "\n")
    assert fast(odd) is journal._FALLBACK
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    assert fast(repo) is journal._FALLBACK


def test_reader_exception_falls_back(repo, spy, monkeypatch):
    def boom(cwd):
        raise RuntimeError("boom")

    monkeypatch.setattr(journal, "_git_head_from_files", boom)
    assert journal._git_head(repo) == real_head(repo) and spy
