"""Completion contracts (Phase 1, evidence-first): an objective closes only on
machine evidence its own work produced, linked by id, from work not in doubt.
Synthetic journals and throwaway git repositories only."""

import asyncio
import subprocess
import sys

import pytest

from syrax import autonomy as auto
from syrax import contracts
from syrax.autonomy import Autonomy, judge
from syrax.devloop import JUDGES
from syrax.journal import Journal, JournalError
from syrax.selfmodel import SelfModel


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def own_task(j, o, goal="work", kind="autonomous"):
    """A task the cycle ran for objective o (as the cycle links it)."""
    t = j.start_task_sync(goal, kind=kind)
    j.record_sync("cycle.completed", {"started": 0, "outcome": "RAN", "objective_id": o["id"], "task_id": t})
    return t


def finish(j, t, text="Done.", status="SUCCESS"):
    j.record_sync("final", {"text": text}, task_id=t)
    j.record_sync("task.completed", {"status": status, "result": text}, task_id=t)


def tool(j, t, name, ok=True, cid="c1", args=None):
    j.record_sync("tool.started", {"id": cid, "name": name, "args": args or {}}, task_id=t)
    j.record_sync("tool.completed" if ok else "tool.failed", {"id": cid, "name": name, "ok": ok, "output": "x"}, task_id=t)


# ——— false-success claims ———

def test_task_success_refuses_a_false_claim_and_is_marked_not_machine_verifiable(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("improve the release tool")  # no check: task_success
    t = own_task(j, o)
    tool(j, t, "journal_query")
    finish(j, t, "The release limitation has been addressed through code optimization.")
    task = j.task(t)
    assert judge(j, o, task)[0] == "DONE"  # the check alone reads it as met
    verdict, c = contracts.assess(j, o, task, "DONE", {"task_status": "SUCCESS"})
    assert verdict == "RETRY" and "claims work the task did not do" in c["reason"]

    t2 = own_task(j, o)
    tool(j, t2, "desktop", args={"action": "system_info"})
    finish(j, t2, "Read the machine: 16 cores, 15.7 GB RAM.")
    verdict, c = contracts.assess(j, o, j.task(t2), "DONE", {"task_status": "SUCCESS"})
    assert verdict == "DONE" and c["attribution"] == "own" and c["evidence"][0]["task_id"] == t2
    assert c["machine_verifiable"] is False  # the gap stays visible in every record

    t3 = own_task(j, o)
    finish(j, t3, "did it")
    verdict, c = contracts.assess(j, o, j.task(t3), "DONE", {"task_status": "SUCCESS"})
    assert verdict == "DONE" and c["evidence"] == [] and "not machine-verifiable" in c["reason"]  # pinned by existing tests; reported as open


def test_a_task_that_is_not_the_objectives_own_cannot_close_it(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("say hi")
    stranger = j.start_task_sync("someone else's task", kind="autonomous")
    tool(j, stranger, "desktop")
    finish(j, stranger, "hi")
    verdict, c = contracts.assess(j, o, None, "DONE", {"task_status": "SUCCESS"})
    assert verdict == "RETRY" and "own task" in c["reason"]


# ——— missing commits, and work products from elsewhere ———

def test_change_released_needs_a_commit_from_its_own_task(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("land the probe", check={"kind": "change_released"})
    t = own_task(j, o)
    finish(j, t, "I have released the probe.")
    verdict, ev = judge(j, o, j.task(t))
    assert verdict == "RETRY" and ev["commits"] == []  # missing commit: the words do not count

    j.record_sync("commit.created", {"commit": "f00d", "files": ["a"], "summary": "x"})  # task-less: nobody's work
    verdict, ev = judge(j, o, None)
    assert verdict == "DONE"  # the judge alone accepts a task-less commit (pinned by test_autonomy)
    verdict, c = contracts.assess(j, o, None, verdict, ev, path="existing")
    assert verdict == "RETRY" and "came from elsewhere" in c["reason"]

    t2 = own_task(j, o)
    j.record_sync("commit.created", {"commit": "beef", "files": ["b"], "summary": "y"}, task_id=t2)
    finish(j, t2, "Released beef.")
    verdict, ev = judge(j, o, j.task(t2))
    verdict, c = contracts.assess(j, o, j.task(t2), verdict, ev)
    assert verdict == "DONE" and c["attribution"] == "own" and [e["sha"] for e in c["evidence"]] == ["beef"]


def test_knowledge_learned_by_another_task_is_not_this_objectives_work(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("learn about matplotlib", check={"kind": "knowledge_stored", "topic": "matplotlib plotting"})
    other = j.start_task_sync("another objective", kind="autonomous")
    j.add_knowledge_sync("matplotlib is a Python plotting library", "web", source_url="http://m", tags=["matplotlib"], task_id=other)
    verdict, ev = judge(j, o, None)
    assert verdict == "DONE"
    assert contracts.assess(j, o, None, verdict, ev, path="existing")[0] == "RETRY"
    t = own_task(j, o)
    k = j.add_knowledge_sync("matplotlib plots data with pyplot", "web", source_url="http://p", tags=["matplotlib", "plotting"], task_id=t)
    finish(j, t, "Learned it.")
    verdict, ev = judge(j, o, j.task(t))
    verdict, c = contracts.assess(j, o, j.task(t), verdict, ev)
    assert verdict == "DONE" and c["attribution"] == "own" and any(e["id"] == k["id"] for e in c["evidence"])


# ——— stale evidence ———

def test_stale_evidence_before_the_objective_does_not_count(tmp_path):
    j = Journal(tmp_path / "j.db")
    old = j.start_task_sync("old", kind="autonomous")
    tool(j, old, "desktop")
    finish(j, old)
    o = j.add_objective_sync("verify desktop", check={"kind": "tool_verified", "tool": "desktop"})
    assert judge(j, o, None)[0] == "RETRY"
    # even if a judge said DONE, the contract finds nothing after the objective was set
    verdict, c = contracts.assess(j, o, None, "DONE", {"used_after_objective": True}, path="existing")
    assert verdict == "RETRY" and "could not be traced" in c["reason"]


# ——— interrupted execution, and recovery after a simulated crash ———

def test_evidence_from_an_interrupted_task_is_not_trusted_until_verified(tmp_path):
    db = tmp_path / "j.db"
    j = Journal(db)
    o = j.add_objective_sync("learn x", check={"kind": "knowledge_stored", "topic": "xylophone tuning"})
    t = own_task(j, o)
    j.add_knowledge_sync("a xylophone is tuned by shaving its bars", "web", source_url="http://x", tags=["xylophone", "tuning"], task_id=t)
    j.close()  # the process dies here: the task never completed
    j = Journal(db)
    j.recover_interrupted()
    assert j.task(t)["status"] == "INTERRUPTED"
    o = j.objective(o["id"])
    verdict, ev = judge(j, o, None)
    assert verdict == "DONE"  # the judge alone would close it
    verdict, c = contracts.assess(j, o, None, verdict, ev, path="existing")
    assert verdict == "RETRY" and "INTERRUPTED" in c["reason"] and "not verified" in c["reason"]


def test_a_commit_left_by_a_crash_counts_only_once_git_has_it(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    (root / "a.txt").write_text("1\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    real = git(root, "rev-parse", "HEAD")
    db = tmp_path / "j.db"
    j = Journal(db)
    o = j.add_objective_sync("land it", check={"kind": "change_released"})
    t = own_task(j, o)
    j.record_sync("commit.created", {"commit": "0123456789abcdef0123456789abcdef01234567", "files": ["a.txt"], "summary": "x"}, task_id=t)
    j.close()
    j = Journal(db)
    j.recover_interrupted()
    o = j.objective(o["id"])
    verdict, ev = judge(j, o, None)
    assert contracts.assess(j, o, None, verdict, ev, path="rejudge", repo_root=root)[0] == "RETRY"  # no such commit in git
    t2 = own_task(j, o)
    j.record_sync("commit.created", {"commit": real, "files": ["a.txt"], "summary": "y"}, task_id=t2)
    j.close()
    j = Journal(db)
    j.recover_interrupted()
    o = j.objective(o["id"])
    verdict, ev = judge(j, o, None)
    verdict, c = contracts.assess(j, o, None, verdict, ev, path="rejudge", repo_root=root)
    assert verdict == "DONE" and any(e.get("verified") == "commit is in the repository history" and e["sha"] == real for e in c["evidence"])


# ——— invalid state transitions and duplicate workers ———

def test_done_is_final_and_a_second_live_process_cannot_take_over(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("x", check={"kind": "verification_green"})
    j.update_objective_sync(o["id"], status="DONE")
    for status in ("OPEN", "ACTIVE", "BLOCKED"):
        with pytest.raises(JournalError):
            j.update_objective_sync(o["id"], status=status)
    t = j.start_task_sync("a")
    finish(j, t)
    with pytest.raises(JournalError):
        j.record_sync("tool.started", {"id": "z", "name": "desktop", "args": {}}, task_id=t)  # a finished task takes no more work


# ——— the cycle: a withdrawn DONE stays open, a kept one links its evidence ———

class Core:
    def __init__(self, journal, script):
        self.journal = journal
        self.selfmodel = SelfModel(journal)
        self.selfmodel.tools_provider = lambda: ["desktop", "terminate"]
        self.busy = False
        self.script = script

    async def submit(self, goal, said, session_id, kind="conversation", **_):
        t = self.journal.start_task_sync(said or goal, kind=kind)
        self.script.pop(0)(self.journal, t)
        return t

    async def wait(self):
        return None


def test_the_cycle_keeps_an_objective_open_when_the_contract_withdraws_done(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    j = Journal(tmp_path / "j.db")
    claim = lambda jj, t: finish(jj, t, "The limitation has been addressed.")
    work = lambda jj, t: (tool(jj, t, "desktop", args={"action": "system_info"}), finish(jj, t, "16 cores."))
    core = Core(j, [claim, work])
    a = Autonomy(core, j)
    a.reflect = False
    a.set_enabled(True)
    o = j.add_objective_sync("report the machine", priority=1)
    rep = asyncio.run(a.run_once())
    got = j.objective(o["id"])
    assert rep.verdict == "RETRY" and got["status"] == "OPEN" and got["evidence"]["contract"]["verdict"] == "RETRY"
    assert "not done:" in got["progress"]["lesson"]
    rep = asyncio.run(a.run_once())
    got = j.objective(o["id"])
    assert rep.verdict == "DONE" and got["status"] == "DONE"
    c = got["evidence"]["contract"]
    assert c["attribution"] == "own" and c["evidence"] and c["evidence"][0]["task_id"] == got["last_task_id"]


# ——— the evaluator stays out of reach ———

def test_the_contract_layer_is_a_judge():
    assert "backend/syrax/contracts.py" in JUDGES
