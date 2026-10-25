"""Audit 2026-10-25, release-policy hole 1: with one brain enabled the cross-brain
review was skipped and an autonomous change committed unreviewed. A review that
could not happen (no second brain, or every reviewer errored or answered
unreadably) now HOLDS the change: outcome REVIEW_UNAVAILABLE, the edits rolled
back exactly like a rejection, the diff kept, review.unavailable journaled,
nothing committed. A rejection still rejects, an approval still commits, the
human's explicit opt-out (SYRAX_REVIEW=0 → {skipped}) still commits, and a
conversation's release (the human is its reviewer) commits as before."""

import asyncio
from pathlib import Path

import pytest

from syrax import devloop
from syrax.devloop import DevLoop, render
from syrax.journal import Journal
from syrax.review import review, unavailable
from syrax.test_devloop import PASS, git, repo
from syrax.test_review_fallback import GOOD, Router

PLAN = {"why": "objective evidence", "risk": "callers of mod", "tests": "test_mod.py"}


def reviewed_loop(tmp_path, root, reviewer, kind="autonomous"):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("improve mod", kind=kind)
    j.record_sync("brain.answered", {"provider": "gemini"}, task_id=t)
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    dl.reviewer = reviewer
    return j, t, dl


async def nobody(info, summary, authors):
    return unavailable("no brain other than the author is enabled", [])


async def all_failed(info, summary, authors):
    return unavailable("no readable review (upstage: Connection error.; groq: unreadable review)", ["upstage", "groq"])


async def reject(info, summary, authors):
    return {"approve": False, "problems": ["weakens_checks"], "reasons": ["the diff deletes a check"], "reviewer": "upstage"}


async def approve(info, summary, authors):
    return {"approve": True, "problems": [], "reasons": [], "reviewer": "upstage"}


async def opted_out(info, summary, authors):
    return {"skipped": "SYRAX_REVIEW=0"}


@pytest.mark.parametrize("reviewer, tried", [(nobody, []), (all_failed, ["upstage", "groq"])])
def test_an_autonomous_change_nobody_could_review_is_held_and_nothing_is_committed(tmp_path, reviewer, tried):
    root = repo(tmp_path)
    head0 = git(root, "rev-parse", "HEAD")
    j, t, dl = reviewed_loop(tmp_path, root, reviewer)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 9\n")
    (root / "backend" / "syrax" / "test_nine.py").write_text("def test_nine(): assert True\n")
    rep = asyncio.run(dl.release("fix VALUE", PLAN))
    assert rep["outcome"] == "REVIEW_UNAVAILABLE" and rep["verification"] == "GREEN"
    assert git(root, "rev-parse", "HEAD") == head0 and git(root, "log", "--format=%s") == "init"  # git log unchanged
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"  # rolled back like a rejection
    assert not (root / "backend" / "syrax" / "test_nine.py").exists()
    assert rep["rollback"]["restored"] == ["backend/syrax/mod.py"] and rep["rollback"]["removed"] == ["backend/syrax/test_nine.py"]
    # the preflight's pytest run leaves a __pycache__ in the throwaway repo (no .gitignore there); the task's files are gone
    assert not {"backend/syrax/mod.py", "backend/syrax/test_nine.py"} & set(devloop.changed_files(root))
    snap = Path(rep["snapshot"]).read_text()
    assert "VALUE = 9" in snap and "# untracked: backend/syrax/test_nine.py" in snap  # the diff is kept for the next attempt
    events = j.events(t)
    kinds = [e["type"] for e in events]
    assert kinds == ["task.started", "brain.answered", "release.planned", "code.changed", "verification.completed",
                     "review.unavailable", "rollback.created"]
    un = next(e["payload"] for e in events if e["type"] == "review.unavailable")
    assert un["brains_tried"] == tried and un["reason"] and un["authors"] == ["gemini"]
    rb = next(e["payload"] for e in events if e["type"] == "rollback.created")
    assert rb["snapshot"] == rep["snapshot"] and rb["restored"] == ["backend/syrax/mod.py"] and "review" in rb["reason"]
    assert rep["review"]["available"] is False
    text = render(rep)
    assert "REVIEW_UNAVAILABLE" in text and "No second brain could review this change" in text
    assert "not committed" in text and "objective stays open" in text and "None" not in text
    exp = j.experiments(limit=1)[0]
    assert exp["result"]["decision"] == "REVIEW_UNAVAILABLE" and exp["verdict"] == "INCONCLUSIVE"
    assert j.archive(limit=1)[0]["decision"] == "REVIEW_UNAVAILABLE" and j.archive(limit=1)[0]["head"] is None


def test_an_eval_release_is_held_too(tmp_path):
    root = repo(tmp_path)
    head0 = git(root, "rev-parse", "HEAD")
    j, t, dl = reviewed_loop(tmp_path, root, nobody, kind="eval")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 9\n")
    rep = asyncio.run(dl.release("fix VALUE"))
    assert rep["outcome"] == "REVIEW_UNAVAILABLE" and git(root, "rev-parse", "HEAD") == head0
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"


def test_a_rejection_still_rejects_and_an_approval_still_commits(tmp_path):
    root = repo(tmp_path)
    j, t, dl = reviewed_loop(tmp_path, root, reject)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 9\n")
    rep = asyncio.run(dl.release("fix VALUE", PLAN))
    assert rep["outcome"] == "REVIEW_REJECTED" and (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"
    assert any(e["type"] == "review.completed" and e["payload"]["approve"] is False for e in j.events(t))
    assert "review.unavailable" not in [e["type"] for e in j.events(t)]
    dl.reviewer = approve
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 9\n")
    rep = asyncio.run(dl.release("fix VALUE", PLAN))
    assert rep["outcome"] == "COMMITTED" and git(root, "rev-parse", "HEAD") == rep["commit"]
    assert git(root, "log", "-1", "--format=%s") == "syrax: fix VALUE"


def test_a_conversation_release_commits_without_a_second_brain(tmp_path):
    """The human is the reviewer of their own conversation's release: today's behaviour stays."""
    root = repo(tmp_path)
    j, t, dl = reviewed_loop(tmp_path, root, nobody, kind="conversation")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 5\n")
    rep = asyncio.run(dl.release("five"))
    assert rep["outcome"] == "COMMITTED" and git(root, "rev-parse", "HEAD") == rep["commit"]
    kinds = [e["type"] for e in j.events(t)]
    assert "review.unavailable" not in kinds and "review.completed" not in kinds and "commit.created" in kinds


def test_the_humans_explicit_opt_out_still_commits(tmp_path):
    """core._cross_review answers {skipped} only for SYRAX_REVIEW=0, the human's decision; that is not a review
    that could not happen, and the test suite relies on it (conftest sets it)."""
    root = repo(tmp_path)
    j, t, dl = reviewed_loop(tmp_path, root, opted_out)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 6\n")
    rep = asyncio.run(dl.release("six", PLAN))
    assert rep["outcome"] == "COMMITTED" and rep["review"] == {"skipped": "SYRAX_REVIEW=0"}


def test_review_says_explicitly_when_no_brain_could_review():
    """review.review never answers a bare skip: no other brain enabled → available False with no brain tried;
    every other brain errored or unreadable → available False naming every brain tried; a readable verdict
    carries no `available` flag."""

    class Store:
        order = ["gemini"]

        def enabled(self, p):
            return True

    class Alone:
        store = Store()

    v = asyncio.run(review(Alone(), {"diff": "x\n", "stat": ""}, "summary", ["gemini"]))
    assert v["available"] is False and v["approve"] is False and v["brains_tried"] == [] and "skipped" not in v
    assert v["problems"] == ["no_review"] and "no brain other than the author is enabled" in v["reasons"][0]
    r = Router({"openrouter": ConnectionError("down"), "upstage": "looks fine", "groq": ConnectionError("413"), "pollinations": "ok!"})
    v = asyncio.run(review(r, {"diff": "x\n", "stat": ""}, "summary", ["gemini"]))
    assert v["available"] is False and v["problems"] == ["no_review"]
    assert v["brains_tried"] == ["openrouter", "upstage", "ollama", "groq", "pollinations"]  # the cooling one was considered too
    good = Router({"openrouter": ConnectionError("down"), "upstage": GOOD})
    v = asyncio.run(review(good, {"diff": "x\n", "stat": ""}, "summary", ["gemini"]))
    assert v["approve"] is True and v["reviewer"] == "upstage" and v.get("available") is not False


def test_the_outcome_is_known_to_the_bookkeeping():
    from syrax import archive

    assert "REVIEW_UNAVAILABLE" in archive.DECISIONS
    assert devloop.DevLoop.DECISION_VERDICT["REVIEW_UNAVAILABLE"] == "INCONCLUSIVE"  # nothing is known to be wrong with the change
