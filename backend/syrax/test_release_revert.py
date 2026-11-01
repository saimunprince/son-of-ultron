"""Audit 2026-11-01 (self-improvement F12): a release of SYRAX's own that made the full quality suite fall stayed in
main until a human looked. When the latest full run regressed by REVERT_MIN_DROP points or more and exactly one own
code commit landed between the runs, its revert is released through the gate and a second brain's review, once."""

import asyncio

from syrax import revert
from syrax.journal import Journal
from syrax.test_devloop import PASS, git, repo
from syrax.test_review_unavailable import approve, reject


def results(n_ok, n=10):
    return [{"id": f"c{i}", "ok": i < n_ok} for i in range(n)]


def setup(tmp_path, own=True, drop=-20.0):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    j.add_quality_run_sync(results(10), 100.0, "BASELINE")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 2\n")
    git(root, "add", "-A")
    git(root, "-c", "user.email=s@x", "-c", "user.name=SYRAX", "commit", "-q", "-m", "syrax: bump VALUE")
    head = git(root, "rev-parse", "HEAD")
    if own:
        t = j.start_task_sync("own work", kind="autonomous")
        j.record_sync("commit.created", {"commit": head, "files": ["backend/syrax/mod.py"], "summary": "bump VALUE"}, task_id=t)
    ok = 10 + int(drop / 10)
    j.add_quality_run_sync(results(ok), ok * 10.0, "REGRESSION", compared_to=1, delta=drop)
    return root, j, head


def test_the_only_own_commit_before_a_regression_is_reverted_through_the_release(tmp_path):
    root, j, head = setup(tmp_path)
    assert revert.candidate(j)["commit"] == head
    rep = asyncio.run(revert.revert(j, root=root, gates=lambda: PASS, reviewer=approve))
    assert rep["outcome"] == "COMMITTED", rep
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"
    ev = [e["payload"] for e in j.recent_events(200) if e["type"] == "release.reverted"]
    assert ev and ev[0]["commit"] == head and ev[0]["outcome"] == "COMMITTED"
    assert revert.candidate(j) is None  # once per commit


def test_a_rejected_revert_changes_nothing(tmp_path):
    root, j, head = setup(tmp_path)
    rep = asyncio.run(revert.revert(j, root=root, gates=lambda: PASS, reviewer=reject))
    assert rep["outcome"] != "COMMITTED" and (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 2\n"
    assert git(root, "rev-parse", "HEAD") == head


def test_a_human_commit_or_a_small_drop_is_not_reverted(tmp_path):
    _, j, _ = setup(tmp_path, own=False)
    assert revert.candidate(j) is None
    _, j2, _ = setup(tmp_path / "b", drop=-3.0)
    assert revert.candidate(j2) is None
