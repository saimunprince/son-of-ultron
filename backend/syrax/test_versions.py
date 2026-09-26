"""Experiments over code versions: worktrees, measured arms, verdict from numbers."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from syrax.journal import Journal
from syrax.versions import CompareVersionsTool, VersionComparer, judge_versions, measure_worktree, parse_pytest, prepare_worktree, render


def test_parse_pytest():
    assert parse_pytest("== 12 passed, 2 failed, 1 error in 3.2s ==") == {"passed": 12, "failed": 3}
    assert parse_pytest("no tests ran") == {"passed": 0, "failed": 0}


def test_judge_versions():
    t = lambda p, f: {"tests": {"passed": p, "failed": f}}
    assert judge_versions({"tests": None}, t(1, 0))[0] == "INCONCLUSIVE"
    assert judge_versions(t(10, 0), t(9, 1))[0] == "BASELINE_BETTER"
    assert judge_versions(t(9, 1), t(10, 0))[0] == "CANDIDATE_BETTER"
    same = judge_versions(t(10, 0), t(10, 0))
    assert same[0] == "NO_DIFFERENCE" and "benchmark not comparable" in same[1]
    b = {**t(10, 0), "bench": {"a": 10.0, "b": 100.0}}
    assert judge_versions(b, {**t(10, 0), "bench": {"a": 10.0, "b": 300.0}})[0] == "BASELINE_BETTER"
    assert judge_versions(b, {**t(10, 0), "bench": {"a": 10.0, "b": 20.0}})[0] == "CANDIDATE_BETTER"
    assert judge_versions(b, {**t(10, 0), "bench": {"a": 11.0, "b": 101.0}})[0] == "NO_DIFFERENCE"


def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "backend" / "syrax").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    g = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=root, check=True, capture_output=True)
    (root / "backend" / "syrax" / "v.py").write_text("V = 1\n")
    g("add", "-A"); g("commit", "-q", "-m", "v1")
    (root / "backend" / "syrax" / "v.py").write_text("V = 2\n")
    g("add", "-A"); g("commit", "-q", "-m", "v2")
    return root


def test_compare_uses_worktrees_and_stores_an_experiment(tmp_path):
    root = repo(tmp_path)
    seen = []

    def fake_measure(wt: Path):
        v = (wt / "backend" / "syrax" / "v.py").read_text().strip()
        seen.append((wt.exists(), v))
        return {"tests": {"passed": 10, "failed": 0 if v == "V = 2" else 1, "exit_code": 0}, "bench": {"x": 1.0}, "notes": []}

    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("compare")
    vc = VersionComparer(j, root=root, measurer=fake_measure, task_id_provider=lambda: t)
    row = asyncio.run(vc.compare("HEAD~1", "HEAD"))
    assert row["verdict"] == "CANDIDATE_BETTER" and "fewer failing tests" in row["conclusion"]
    assert [v for _, v in seen] == ["V = 1", "V = 2"]  # each arm measured in its own checkout
    assert row["baseline"]["ref"] == "HEAD~1" and row["candidate"]["sha"] != row["baseline"]["sha"] and row["candidate"]["ms"] >= 0
    wts = subprocess.run(["git", "worktree", "list"], cwd=root, capture_output=True, text=True).stdout.strip().splitlines()
    assert len(wts) == 1  # temporary worktrees removed
    kinds = [e["type"] for e in j.events(t)]
    assert kinds[-2:] == ["experiment.started", "experiment.completed"]
    assert "VERSION EXPERIMENT #1 CANDIDATE_BETTER" in render(row)
    with pytest.raises(ValueError, match="same commit"):
        asyncio.run(vc.compare("HEAD", "HEAD"))
    with pytest.raises(ValueError, match="unknown ref"):
        asyncio.run(vc.compare("nope", "HEAD"))


def test_measure_worktree_without_backend_is_inconclusive(tmp_path):
    out = measure_worktree(tmp_path)
    assert out["tests"] is None and "no backend/syrax" in out["notes"][0]


def test_tool_reports_and_refuses(tmp_path):
    assert asyncio.run(CompareVersionsTool().execute(base="a", candidate="b")).error
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    tool = CompareVersionsTool()
    tool.comparer = VersionComparer(j, root=root, measurer=lambda wt: {"tests": {"passed": 1, "failed": 0}, "bench": None, "notes": []})
    out = asyncio.run(tool.execute(base="HEAD~1", candidate="HEAD"))
    assert not out.error and "NO_DIFFERENCE" in out.output
    assert "refused" in asyncio.run(tool.execute(base="HEAD", candidate="HEAD")).error


def test_prepare_worktree_copies_untracked_runtime_config(tmp_path):
    src = tmp_path / "src"
    (src / "backend" / "config").mkdir(parents=True)
    (src / "backend" / "config" / "config.toml").write_text("[llm]\nmodel='x'\n")
    wt = tmp_path / "wt"
    (wt / "backend").mkdir(parents=True)
    assert prepare_worktree(wt, src) == ["backend/config/config.toml"]
    assert (wt / "backend" / "config" / "config.toml").read_text().startswith("[llm]")
    assert prepare_worktree(wt, src) == []  # never overwrites
