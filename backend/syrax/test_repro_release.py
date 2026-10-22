"""Brief Factory (2026-10-22): a brief filed with a judge-proven test lands with exactly that test. Live 2026-10-19:
SYRAX's release of objective 291 dropped one of the brief's tests (and apply_patch dropped part of the fix), and
2431cec dropped another; the human found it by diffing the commit against the brief. Now the release refuses a
missing, changed or no-longer-failing test and any file outside the brief, the judge checks the committed test
byte for byte, and the cycle writes the proven test into the task's worktree so no model retypes it."""

import asyncio
import sys

import pytest

from syrax import autonomy as auto
from syrax import repro
from syrax.autonomy import RELEASE_STEPS, Autonomy, judge
from syrax.core import write_seed
from syrax.devloop import DevLoop
from syrax.journal import Journal
from syrax.test_autonomy_retry import BudgetCore
from syrax.test_devloop import git
from syrax.test_repro_prove import FIX, REPRO, TEST, shaped_repo
from syrax.verify import Gate

PASS = [Gate("ok", [sys.executable, "-c", "pass"])]
FIXED = "def add(a, b):\n    return a + b\n"


def filed(j, root, text=REPRO):
    proof = {"verdict": "RED", "base": git(root, "rev-parse", "HEAD"), "sha256": repro.test_sha(text), "test": TEST,
             "red": {"summary": "1 failed, 0 errors, 0 passed"}}
    return repro.file_brief(j, "add() subtracts", "test", TEST, text, ["backend/syrax/calc.py"], proof)


def isolated_task(tmp_path):
    root = shaped_repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    o = filed(j, root)
    j.update_objective_sync(o["id"], status="ACTIVE", note="cycle picked this objective")
    t = j.start_task_sync(o["goal"], kind="autonomous")
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    dl.begin_task()
    wt = dl.isolate(t)
    return root, j, o, dl, wt


def test_the_brief_carries_the_test_its_hash_and_the_proof(tmp_path):
    root = shaped_repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    o = filed(j, root)
    rp = o["check_spec"]["repro"]
    assert o["check_spec"]["kind"] == "change_released" and o["check_spec"]["files"] == ["backend/syrax/calc.py", TEST]
    assert rp["test"] == TEST and rp["sha256"] == repro.test_sha(REPRO) and rp["text"] == REPRO
    assert o["priority"] == 1 and o["key"] == f"repro-brief:{rp['sha256'][:16]}"
    assert REPRO in o["goal"] and "Do not change it" in o["goal"]
    assert filed(j, root) is None  # the same test is filed once


def test_the_release_holds_the_brief_to_its_test(tmp_path):
    root, j, o, dl, wt = isolated_task(tmp_path)
    (wt / "backend" / "syrax" / "calc.py").write_text(FIXED)
    with pytest.raises(ValueError, match="is not in this release"):
        dl.inspect()
    (wt / TEST).write_text(REPRO.replace("5", "5  # same"))
    with pytest.raises(ValueError, match="differs from the filed test"):
        dl.inspect()
    (wt / TEST).write_bytes(REPRO.encode())
    (wt / "backend" / "syrax" / "other.py").write_text("X = 1\n")
    with pytest.raises(ValueError, match="other.py is outside it"):
        dl.inspect()
    (wt / "backend" / "syrax" / "other.py").unlink()
    info = dl.inspect()  # the filed test, still red on the task's base, and the fix
    assert sorted(info["files"]) == ["backend/syrax/calc.py", TEST]


def test_a_test_that_no_longer_fails_on_the_base_is_not_released(tmp_path):
    root, j, o, dl, wt = isolated_task(tmp_path)
    (root / "backend" / "syrax" / "calc.py").write_text(FIXED)  # someone fixed it on main first
    git(root, "commit", "-qam", "fixed elsewhere")
    git(wt, "checkout", "-q", "--detach", git(root, "rev-parse", "HEAD"))
    (wt / TEST).write_bytes(REPRO.encode())
    (wt / "backend" / "syrax" / "calc.py").write_text(FIXED + "\n")
    with pytest.raises(ValueError, match="no longer fails"):
        dl.inspect()


def commit(j, t, sha, files):
    j.record_sync("commit.created", {"commit": sha, "files": files, "summary": "x", "verification_id": 1}, task_id=t)


def test_the_judge_accepts_only_the_committed_test_that_was_filed(tmp_path, monkeypatch):
    root = shaped_repo(tmp_path)
    monkeypatch.setattr(auto, "REPO_ROOT_PATH", root)
    j = Journal(tmp_path / "j.db")
    o = filed(j, root)
    (root / "backend" / "syrax" / "calc.py").write_text(FIXED)
    (root / TEST).write_bytes(REPRO.replace("== 5", "== 5 or True").encode())  # a weakened test
    git(root, "add", "-A")
    git(root, "commit", "-qm", "weakened")
    t = j.start_task_sync(o["goal"], kind="autonomous")
    commit(j, t, git(root, "rev-parse", "HEAD"), o["check_spec"]["files"])
    verdict, ev = judge(j, o, j.task(t))
    assert verdict == "RETRY" and ev["repro"]["ok"] is False
    (root / TEST).write_bytes(REPRO.encode())
    git(root, "commit", "-qam", "the filed test")
    j.record_sync("cycle.completed", {"objective_id": o["id"], "task_id": t, "outcome": "RAN"})
    t2 = j.start_task_sync(o["goal"], kind="autonomous")
    commit(j, t2, git(root, "rev-parse", "HEAD"), [TEST])
    verdict, ev = judge(j, o, j.task(t2))
    assert verdict == "DONE" and ev["repro"]["ok"] is True


def test_the_cycle_writes_the_proven_test_into_the_task_and_never_anything_else(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    j = Journal(tmp_path / "j.db")
    seeds = []

    class SeedCore(BudgetCore):
        async def submit(self, goal, said, session_id, kind="conversation", max_steps=None, seed=None):
            seeds.append(seed)
            return await super().submit(goal, said, session_id, kind, max_steps)

    core = SeedCore(j)
    a = Autonomy(core, j)
    a.reflect = False
    a.set_enabled(True)
    root = shaped_repo(tmp_path)
    o = filed(j, root)
    core.script = [lambda t: j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)]
    rep = asyncio.run(a.run_once())
    assert rep.objective_id == o["id"] and core.submitted[0][2] == RELEASE_STEPS
    assert seeds == [{TEST: REPRO}]
    wt = tmp_path / "wt"
    (wt / "backend" / "syrax").mkdir(parents=True)
    (wt / "backend" / "syrax" / "test_kept.py").write_text("old\n")
    written = write_seed(wt, {TEST: REPRO.replace("\n", "\r\n"), "backend/syrax/calc.py": "evil", "../x.py": "evil",
                              "backend/syrax/test_kept.py": "new"})
    assert written == [TEST] and (wt / TEST).read_bytes() == REPRO.encode()
    assert (wt / "backend" / "syrax" / "test_kept.py").read_text() == "old\n" and not (wt / "backend" / "syrax" / "calc.py").exists()
