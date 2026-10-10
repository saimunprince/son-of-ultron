"""Every release attempt leaves a trustworthy experiment record (Phase 1):
objective id, source revision, environment, test results, artifacts and the
release decision; the verdict comes from the outcome, not from the summary.
Throwaway git repositories and fake gates only."""

import asyncio
import subprocess
import sys

import pytest

from syrax.autonomy import judge
from syrax.devloop import DevLoop
from syrax.journal import Journal
from syrax.verify import Gate

PASS = [Gate("ok", [sys.executable, "-c", "pass"])]
FAIL = [Gate("ok", [sys.executable, "-c", "pass"]), Gate("tests", [sys.executable, "-c", "import sys; print('1 failed'); sys.exit(1)"])]
PLAN = {"why": "objective evidence", "risk": "callers of mod", "tests": "test_new.py"}


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "backend" / "syrax").mkdir(parents=True)
    git(root, "init", "-q")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 1\n")
    (root / "backend" / "syrax" / "quality.py").write_text("CHECK = 'research'\n")
    (root / "backend" / "syrax" / "contracts.py").write_text("STRICT = True\n")
    (root / "backend" / "syrax" / "test_mod.py").write_text("def test_v(): assert True\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


def setup(tmp_path, gates):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("land a change", check={"kind": "change_released"})
    j.update_objective_sync(o["id"], status="ACTIVE")
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] land a change", kind="autonomous")
    j.record_sync("cycle.completed", {"started": 0, "outcome": "RAN", "objective_id": o["id"], "task_id": t})
    dl = DevLoop(j, root=root, gates=lambda: gates, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    return root, j, o, t, dl


def test_a_committed_release_is_recorded_with_everything_needed_to_reproduce_it(tmp_path):
    root, j, o, t, dl = setup(tmp_path, PASS)
    head0 = git(root, "rev-parse", "HEAD")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 2\n")
    (root / "backend" / "syrax" / "test_new.py").write_text("def test_n(): assert True\n")
    rep = asyncio.run(dl.release("bump VALUE", PLAN))
    assert rep["outcome"] == "COMMITTED"
    x = j.experiments(limit=1)[0]
    r = x["result"]
    assert x["verdict"] == "CANDIDATE_BETTER" and x["metric"] == "release_gate" and x["objective"] == str(o["id"])
    assert r["decision"] == "COMMITTED" and r["objective_id"] == o["id"] and r["task_id"] == t
    assert r["source_revision"] == head0 and x["baseline"] == {"git_head": head0}
    assert r["environment"]["python"] == sys.version.split()[0] and r["environment"]["platform"]
    assert r["tests"]["status"] == "GREEN" and r["tests"]["gates"] and r["tests"]["verification_id"] == rep["verification_id"]
    assert r["artifacts"]["commit"] == rep["commit"] and r["artifacts"]["snapshot"] and r["artifacts"]["diff_sha256"]
    assert "backend/syrax/mod.py" in r["artifacts"]["files"] and r["plan"] == PLAN
    assert x["conclusion"].startswith("committed ")
    # the task's own event sequence is the release's; the experiment event stands alone
    assert [e["type"] for e in j.events(t)][-1] == "commit.created"


def test_a_failed_experiment_never_becomes_a_success_whatever_it_says(tmp_path):
    root, j, o, t, dl = setup(tmp_path, FAIL)
    head0 = git(root, "rev-parse", "HEAD")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 3\n")
    rep = asyncio.run(dl.release("Fixed everything; all tests pass and the capability is verified", PLAN))
    assert rep["outcome"] == "ROLLED_BACK" and git(root, "rev-parse", "HEAD") == head0
    x = j.experiments(limit=1)[0]
    assert x["verdict"] == "BASELINE_BETTER" and x["result"]["decision"] == "ROLLED_BACK"
    assert x["result"]["tests"]["failing"] == ["tests"] and x["next_action"]
    assert x["conclusion"].startswith("rolled back: gate")  # computed from the outcome, not from the summary
    assert judge(j, j.objective(o["id"]), j.task(t))[0] == "RETRY"  # no commit: the objective stays open


@pytest.mark.parametrize("path,text,why", [
    ("backend/syrax/contracts.py", "STRICT = False\n", "judges SYRAX's own work"),
    ("backend/syrax/quality.py", "CHECK = 'know'\n", "judges SYRAX's own work"),
    ("backend/syrax/test_mod.py", "def test_v(): pass\n", "existing tests are the contract"),
])
def test_an_attempt_on_the_evaluator_or_a_trusted_test_is_refused_and_recorded(tmp_path, path, text, why):
    root, j, o, t, dl = setup(tmp_path, PASS)
    head0 = git(root, "rev-parse", "HEAD")
    (root / path).write_text(text)
    with pytest.raises(ValueError, match=why):
        asyncio.run(dl.release("make the check pass", PLAN))
    assert git(root, "rev-parse", "HEAD") == head0 and not j.verifications()  # the gate never ran
    x = j.experiments(limit=1)[0]
    assert x["verdict"] == "BASELINE_BETTER" and x["result"]["decision"] == "REFUSED" and why in x["result"]["reason"]
    assert x["result"]["objective_id"] == o["id"] and x["conclusion"].startswith("refused before the gate")
