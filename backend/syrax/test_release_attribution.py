"""EVOLUTION_PLAN wave 2 (directions 5 causal reasoning, 6 counterfactual reasoning, 90 self-improvement verification):
a quality regression became an objective "find why", with no word about which change came before it. The objective now
names the changes made between the previous run and the regressed one (SYRAX's own releases from the journal, and the
commits git shows between the runs' heads) as the first suspects, and says how to test one against its parent."""

import time

from syrax.autonomy import derive_objectives, suspects
from syrax.journal import Journal
from syrax.selfmodel import SelfModel

CASES_OK = [{"id": f"c{i}", "ok": True} for i in range(10)]
CASES_BAD = [{"id": f"c{i}", "ok": i < 7} for i in range(10)]


def setup(tmp_path):
    j = Journal(tmp_path / "j.db", repo_root=tmp_path)  # no git here: the journal's own release list is used
    j.add_quality_run_sync(CASES_OK, 100.0, "BASELINE")
    time.sleep(0.01)
    t = j.start_task_sync("release a change")
    j.record_sync("commit.created", {"commit": "abc1234def5678", "files": {"backend/syrax/agent.py": "M"},
                                     "summary": "shorter tool manual"}, task_id=t)
    time.sleep(0.01)
    j.add_quality_run_sync(CASES_BAD, 70.0, "REGRESSION", compared_to=1, delta=-30.0)
    return j


def test_the_releases_between_the_runs_are_the_suspects(tmp_path):
    j = setup(tmp_path)
    runs = j.quality_runs(limit=2)
    (s,) = suspects(j, runs[0], runs[1])
    assert s["commit"] == "abc1234def5678" and s["by"] == "SYRAX" and s["summary"] == "shorter tool manual"
    assert suspects(j, runs[0], None) == []


def test_the_regression_objective_names_them_and_how_to_test_one(tmp_path):
    j = setup(tmp_path)
    derive_objectives(j, SelfModel(j))
    o = next(x for x in j.objectives(limit=50) if str(x.get("key") or "").startswith("quality-regression:"))
    assert "abc1234d shorter tool manual" in o["goal"] and "compare_versions" in o["goal"]
    assert o["evidence"]["suspects"][0]["commit"] == "abc1234def5678"


def test_git_adds_every_commit_between_the_runs_heads(tmp_path):
    import subprocess

    from syrax.journal import BACKEND_ROOT

    root = BACKEND_ROOT.parent
    heads = subprocess.run(["git", "rev-list", "--max-count=3", "HEAD"], cwd=root, capture_output=True, text=True).stdout.split()
    if len(heads) < 3:
        return  # a shallow checkout: nothing to range over
    j = Journal(tmp_path / "j.db")
    now = time.time()
    found = suspects(j, {"ts": now, "git_head": heads[0]}, {"ts": now - 60, "git_head": heads[2]})
    assert {s["commit"] for s in found} == {heads[0], heads[1]}  # the two commits after the earlier run's head
    assert all(s["summary"] for s in found)
