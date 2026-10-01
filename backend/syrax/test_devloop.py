"""Autonomous development loop tests on a throwaway git repository with fake gates."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from syrax.devloop import DevLoop, ReleaseTool, changed_files, render, scope_problems
from syrax.journal import Journal
from syrax.verify import Gate


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "backend" / "syrax").mkdir(parents=True)
    (root / "docs").mkdir()
    git(root, "init", "-q")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 1\n")
    (root / "README.md").write_text("# repo\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


PASS = [Gate("ok", [sys.executable, "-c", "pass"])]
FAIL = [Gate("ok", [sys.executable, "-c", "pass"]), Gate("tests", [sys.executable, "-c", "import sys; print('1 failed: VALUE should be 1'); sys.exit(1)"])]


def loop(tmp_path, root, gates):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("improve mod")
    dl = DevLoop(j, root=root, gates=lambda: gates, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    return j, t, dl


def test_green_change_is_committed_and_journaled(tmp_path):
    root = repo(tmp_path)
    head0 = git(root, "rev-parse", "HEAD")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 2\n")
    (root / "docs" / "NOTE.md").write_text("changed\n")
    j, t, dl = loop(tmp_path, root, PASS)
    rep = asyncio.run(dl.release("bump VALUE"))
    assert rep["outcome"] == "COMMITTED" and rep["verification"] == "GREEN"
    head1 = git(root, "rev-parse", "HEAD")
    assert head1 != head0 and rep["commit"] == head1
    msg = git(root, "log", "-1", "--format=%B")
    assert msg.startswith("syrax: bump VALUE") and f"Verified-By: syrax.verify #{rep['verification_id']}" in msg
    assert changed_files(root) == {}  # tree clean after commit
    kinds = [e["type"] for e in j.events(t)]
    assert kinds == ["task.started", "release.planned", "code.changed", "verification.completed", "commit.created"]
    assert rep["push"]["ok"] is None and "SYRAX_AUTOPUSH" in rep["push"]["output"]
    assert j.verifications()[0]["status"] == "GREEN" and j.verifications()[0]["task_id"] == t
    assert "Committed" in render(rep)
    assert list((tmp_path / "rb").glob("*.patch"))  # snapshot kept even on success


def test_blocked_change_is_rolled_back_with_evidence(tmp_path):
    root = repo(tmp_path)
    head0 = git(root, "rev-parse", "HEAD")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 3\n")
    (root / "backend" / "syrax" / "new.py").write_text("x = 1\n")
    j, t, dl = loop(tmp_path, root, FAIL)
    rep = asyncio.run(dl.release("break things"))
    assert rep["outcome"] == "ROLLED_BACK" and rep["verification"] == "BLOCKED"
    assert git(root, "rev-parse", "HEAD") == head0
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"
    assert not (root / "backend" / "syrax" / "new.py").exists()
    assert rep["rollback"] == {"restored": ["backend/syrax/mod.py"], "removed": ["backend/syrax/new.py"], "clean": True}
    assert rep["failing"][0]["name"] == "tests" and "VALUE should be 1" in rep["failing"][0]["evidence"]
    kinds = [e["type"] for e in j.events(t)]
    assert kinds == ["task.started", "release.planned", "code.changed", "verification.completed", "rollback.created"]
    snap = Path(rep["snapshot"]).read_text()
    assert "VALUE = 3" in snap and "# untracked: backend/syrax/new.py" in snap  # the attempt is preserved for study
    text = render(rep)
    assert "ROLLED_BACK" in text and "change approach" in text and "VALUE should be 1" in text


def test_refusals(tmp_path):
    root = repo(tmp_path)
    j, t, dl = loop(tmp_path, root, PASS)
    with pytest.raises(ValueError, match="nothing to release"):
        asyncio.run(dl.release("x"))
    with pytest.raises(ValueError, match="summary"):
        asyncio.run(dl.release(" "))
    (root / "backend" / "config").mkdir()
    (root / "backend" / "config" / "config.toml").write_text("secret\n")
    with pytest.raises(ValueError, match="forbidden"):
        asyncio.run(dl.release("x"))
    (root / "backend" / "config" / "config.toml").unlink()
    (root / "other.txt").write_text("x\n")
    with pytest.raises(ValueError, match="outside the self-modification scope"):
        asyncio.run(dl.release("x"))
    (root / "other.txt").unlink()
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 1\ntoken = 'ghp_" + "A" * 36 + "'\n")
    with pytest.raises(ValueError, match="diff scan"):
        asyncio.run(dl.release("x"))
    assert j.count("verifications") == 0  # nothing ran the gate
    assert scope_problems({"docs/x.md": "M", "backend/syrax/a.py": "??"}) == []


def test_autopush_to_a_bare_remote(tmp_path, monkeypatch):
    root = repo(tmp_path)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    git(root, "remote", "add", "origin", str(bare))
    git(root, "push", "-q", "origin", "HEAD")
    (root / "README.md").write_text("# repo\nmore\n")
    monkeypatch.setenv("SYRAX_AUTOPUSH", "1")
    j, t, dl = loop(tmp_path, root, PASS)
    rep = asyncio.run(dl.release("readme"))
    assert rep["outcome"] == "COMMITTED" and rep["push"]["ok"] is True
    remote_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=bare, capture_output=True, text=True).stdout.strip()
    assert remote_head == rep["commit"]
    kinds = [e["type"] for e in j.events(t)]
    assert kinds[-2:] == ["push.started", "push.completed"]


def test_release_tool_reports_and_refuses(tmp_path):
    assert asyncio.run(ReleaseTool().execute(summary="x")).error
    root = repo(tmp_path)
    j, t, dl = loop(tmp_path, root, FAIL)
    tool = ReleaseTool(); tool.loop = dl
    out = asyncio.run(tool.execute(summary="x"))
    assert out.error and "nothing to release" in out.error
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 9\n")
    out = asyncio.run(tool.execute(summary="nine"))
    assert not out.error and "ROLLED_BACK" in out.output and (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"


def test_release_refuses_python_that_does_not_compile_before_running_the_gate(tmp_path):
    root = repo(tmp_path)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = (1\n")
    j, t, dl = loop(tmp_path, root, PASS)
    with pytest.raises(ValueError, match="does not compile"):
        asyncio.run(dl.release("broken"))
    assert j.count("verifications") == 0  # the gate never ran
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = (1\n"  # refusal does not touch the tree


def test_autonomous_work_cannot_release_changes_to_its_judges(tmp_path):
    """Live 2026-10-01: SYRAX weakened its own quality case to make it pass."""
    from syrax.devloop import judge_problems
    root = repo(tmp_path)
    (root / "backend" / "syrax" / "quality.py").write_text("CHECK = 'research'\n")
    (root / "backend" / "syrax" / "test_mod.py").write_text("def test_v(): assert True\n")
    git(root, "add", "-A"); git(root, "commit", "-q", "-m", "judges")
    j = Journal(tmp_path / "j.db")
    auto = j.start_task_sync("make research_cite pass", kind="autonomous")
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: auto, snapshot_dir=tmp_path / "rb")
    (root / "backend" / "syrax" / "quality.py").write_text("CHECK = 'know'\n")
    with pytest.raises(ValueError, match="judges SYRAX's own work"):
        asyncio.run(dl.release("expect the tool that ran"))
    git(root, "checkout", "--", ".")
    (root / "backend" / "syrax" / "test_mod.py").write_text("def test_v(): pass\n")
    with pytest.raises(ValueError, match="existing tests are the contract"):
        asyncio.run(dl.release("loosen the test"))
    git(root, "checkout", "--", ".")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 3\n")
    (root / "backend" / "syrax" / "test_new.py").write_text("def test_n(): assert True\n")
    assert asyncio.run(dl.release("fix behaviour, add a test", {"why": "objective evidence", "risk": "callers of mod", "tests": "test_mod.py"}))["outcome"] == "COMMITTED"
    human = j.start_task_sync("human asks to change the case", kind="conversation")
    dl.task_id_provider = lambda: human
    dl.begin_task()
    (root / "backend" / "syrax" / "quality.py").write_text("CHECK = 'research or know'\n")
    assert asyncio.run(dl.release("human-approved case change"))["outcome"] == "COMMITTED"
    assert judge_problems({"docs/x.md": "M", "backend/syrax/test_x.py": "??"}) == []


def test_an_autonomous_release_needs_another_brain_to_approve(tmp_path):
    """OpenRig's dev-check seat: the gate proves it runs, a second brain checks it is what it claims."""
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("improve mod", kind="autonomous")
    j.record_sync("brain.answered", {"provider": "gemini"}, task_id=t)
    seen = {}

    async def reject(info, summary, authors):
        seen["authors"] = authors
        return {"approve": False, "reasons": ["the summary says fix but the diff deletes a check"], "reviewer": "upstage"}

    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    dl.reviewer = reject
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 9\n")
    rep = asyncio.run(dl.release("fix VALUE", {"why": "objective evidence", "risk": "callers of mod", "tests": "test_mod.py"}))
    assert rep["outcome"] == "REVIEW_REJECTED" and seen["authors"] == ["gemini"]
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"  # rolled back
    assert any(e["type"] == "review.completed" and e["payload"]["approve"] is False for e in j.events(t))

    async def approve(info, summary, authors):
        return {"approve": True, "reasons": ["matches the summary"], "reviewer": "upstage"}

    dl.reviewer = approve
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 9\n")
    assert asyncio.run(dl.release("fix VALUE", {"why": "objective evidence", "risk": "callers of mod", "tests": "test_mod.py"}))["outcome"] == "COMMITTED"


def test_review_parsing_and_reviewer_choice():
    from syrax.review import parse, reviewers

    ok = parse('{"weakens_checks": false, "clear_bug": false, "secret": false, "matches_summary": true, "reasons": []}')
    assert ok["approve"] is True and ok["problems"] == []
    sneaky = parse('{"weakens_checks": true, "clear_bug": false, "secret": false, "matches_summary": true, "approve": true}')
    assert sneaky["approve"] is False and sneaky["problems"] == ["weakens_checks"]  # the model's own "approve" is ignored
    assert parse("looks good to me") is None and parse('{"weakens_checks": "no"}') is None

    class S:
        order = ["gemini", "upstage", "groq"]

        def enabled(self, p):
            return p != "groq"

    class R:
        store = S()

    assert reviewers(R(), ["gemini"]) == ["upstage"]


def test_autonomous_release_needs_a_change_plan_and_journals_its_impact(tmp_path):
    """Phase 4: evidence-driven engineering, not random rewriting."""
    root = repo(tmp_path)
    (root / "docs" / "system_map.json").write_text(json.dumps({"components": [
        {"component": "Mod", "code": ["backend/syrax/mod.py"], "tests": ["backend/syrax/test_mod.py (unit)"]}]}))
    git(root, "add", "-A"); git(root, "commit", "-q", "-m", "map")
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("improve mod", kind="autonomous")
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 4\n")
    with pytest.raises(ValueError, match="missing: why, risk, tests"):
        asyncio.run(dl.release("bump VALUE"))
    plan = {"why": "objective 7: VALUE must be 4", "risk": "callers reading VALUE", "tests": "test_mod.py"}
    assert asyncio.run(dl.release("bump VALUE", plan))["outcome"] == "COMMITTED"
    ev = [e for e in j.events(t) if e["type"] == "release.planned"][-1]["payload"]
    assert ev["plan"] == plan and ev["components"] == ["Mod"] and ev["component_tests"] == ["backend/syrax/test_mod.py"]


def test_owned_files_follow_what_the_task_actually_ran():
    from syrax.devloop import owned_files
    changed = {"backend/syrax/brains.py": "M", "backend/syrax/mod.py": "M", "docs/x.md": "??"}
    # a browser/desktop verification task that touched no file owns nothing, even if the tree changed meanwhile
    assert owned_files(changed, ["browser_exec", "self_inspect"], []) == {}
    # editor only: exactly the journaled paths (Windows separators normalised)
    assert owned_files(changed, ["str_replace_editor"], ["backend\\syrax\\mod.py"]) == {"backend/syrax/mod.py": "M"}
    # python may write anywhere: every non-baseline change is the task's
    assert owned_files(changed, ["python_execute"], []) == changed


def test_release_and_rollback_never_touch_a_humans_uncommitted_work(tmp_path):
    root = repo(tmp_path)
    (root / "README.md").write_text("# repo\nhuman edit in progress\n")  # dirty before the task
    j, t, dl = loop(tmp_path, root, FAIL)
    dl.begin_task()
    with pytest.raises(ValueError, match="predate this task"):
        asyncio.run(dl.release("x"))
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 7\n")  # the task's own edit
    rep = asyncio.run(dl.release("seven"))
    assert rep["outcome"] == "ROLLED_BACK" and list(rep["files"]) == ["backend/syrax/mod.py"]
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"
    assert (root / "README.md").read_text() == "# repo\nhuman edit in progress\n"  # untouched
    dl.gates = lambda: PASS
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 8\n")
    rep = asyncio.run(dl.release("eight"))
    assert rep["outcome"] == "COMMITTED" and rep["files"] == {"backend/syrax/mod.py": "M"}
    assert git(root, "status", "--porcelain") == "M README.md"  # the human's change stays uncommitted (helper strips)
