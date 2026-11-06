"""Live 2026-11-06: "What can you do that you could not do a week ago?" was answered "I cannot answer"; git holds
every change SYRAX received. self_inspect section=changes lists the last week's commits by kind."""

import subprocess

from syrax.journal import Journal
from syrax.selfmodel import SelfModel


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"})


def test_changes_lists_the_week_by_kind(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    for msg in ("feat(reminders): daily reminders", "fix(data): numbers sort as numbers", "docs: progress"):
        (repo / "f.txt").write_text(msg)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", msg)
    j = Journal(tmp_path / "j.db")
    try:
        ch = SelfModel(j, repo_root=repo).snapshot("changes")["changes"]
    finally:
        j.close()
    assert ch["commits"] == 3 and ch["by_kind"] == {"feat": 1, "fix": 1, "docs": 1}
    assert ch["log"][0].endswith("docs: progress") and "daily reminders" in ch["log"][-1]
