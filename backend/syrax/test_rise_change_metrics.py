"""Audit 2026-10-27 (open item 2): objective_success counted research closures like code changes, and nothing showed
that 88.7 % of the commits were made by people. Two metrics: objectives done that needed a landed change, and the
human share of the repository's commits in the window."""

import subprocess
import time

from syrax import journal as jmod
from syrax import rise
from syrax.journal import Journal

DAY = 86400


def test_only_objectives_that_needed_a_landed_change_count(tmp_path, monkeypatch):
    now = time.time()
    monkeypatch.setattr(jmod, "_now", lambda: now - DAY)
    j = Journal(tmp_path / "j.db")
    for kind in ("knowledge_stored", "knowledge_stored", "quality_case_passes", "repro_proven", "tool_verified"):
        o = j.add_objective_sync(f"goal {kind}", None, 3, "selfmodel", {"kind": kind, "case": "x"}, key=f"k-{kind}-{time.perf_counter()}")
        j.update_objective_sync(o["id"], status="DONE", bump_attempts=True)
    m = {r["id"]: r for r in rise.measure(tmp_path / "j.db", now=now)["metrics"]}
    assert m["change_objectives"]["last"]["value"] == 2.0
    assert "2 of 5" in m["change_objectives"]["last"]["detail"]


def test_the_human_share_of_commits_reads_git(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args, author="Prince"):
        env = {"GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": "a@x", "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": "a@x"}
        import os
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env={**os.environ, **env})

    git("init", "-q")
    for i, who in enumerate(["Prince", "SYRAX", "Prince", "Prince"]):
        (repo / f"f{i}").write_text(str(i))
        git("add", f"f{i}")
        git("commit", "-q", "-m", f"c{i}", author=who)
    monkeypatch.setattr(rise, "REPO_ROOT", repo)
    now = time.time()
    value, how = rise.human_commit_share(None, now - DAY, now + 60)
    assert value == 75.0 and how == "3/4"
    assert rise.human_commit_share(None, now - 3 * DAY, now - 2 * DAY) == (None, "no data")
