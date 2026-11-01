"""Owner's spec 2026-11-01 (F10): a release asked for in a conversation went to main with no second brain. It is
reviewed now by a brain that did not write it; held (no reviewer, or rejected), nothing is committed and, unlike
own work, the edits are not rolled back: they stay in the working tree, and the release report shows the human the
diff and the findings."""

import asyncio

from syrax import devloop
from syrax.review import reviewers
from syrax.test_devloop import git, repo
from syrax.test_review_model_family import Router as FamilyRouter
from syrax.test_review_unavailable import PLAN, all_failed, approve, nobody, reject, reviewed_loop


def change(root):
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 9\n")


def test_an_approved_conversation_release_commits(tmp_path):
    root = repo(tmp_path)
    j, t, dl = reviewed_loop(tmp_path, root, approve, kind="conversation")
    change(root)
    rep = asyncio.run(dl.release("set VALUE to 9", PLAN))
    assert rep["outcome"] == "COMMITTED"
    assert [e["payload"]["approve"] for e in j.events(t) if e["type"] == "review.completed"] == [True]


def test_a_rejected_conversation_release_is_held_with_the_diff_and_findings(tmp_path):
    root = repo(tmp_path)
    head0 = git(root, "rev-parse", "HEAD")
    j, t, dl = reviewed_loop(tmp_path, root, reject, kind="conversation")
    change(root)
    rep = asyncio.run(dl.release("set VALUE to 9", PLAN))
    assert rep["outcome"] == "REVIEW_REJECTED" and rep["held"] is True
    assert git(root, "rev-parse", "HEAD") == head0  # nothing committed
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 9\n"  # the human's edits stay
    text = devloop.render(rep)
    assert "Not committed" in text and "the diff deletes a check" in text and "+VALUE = 9" in text
    assert [e["payload"]["outcome"] for e in j.events(t) if e["type"] == "release.held"] == ["REVIEW_REJECTED"]


def test_a_conversation_release_nobody_could_review_is_held(tmp_path):
    for i, reviewer in enumerate((nobody, all_failed)):
        root = repo(tmp_path / str(i))
        head0 = git(root, "rev-parse", "HEAD")
        j, t, dl = reviewed_loop(tmp_path / str(i), root, reviewer, kind="conversation")
        change(root)
        rep = asyncio.run(dl.release("set VALUE to 9", PLAN))
        assert rep["outcome"] == "REVIEW_UNAVAILABLE" and rep["held"] is True
        assert git(root, "rev-parse", "HEAD") == head0 and (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 9\n"
        assert "no second brain could review it" in devloop.render(rep)


def test_the_author_never_reviews_its_own_change(tmp_path):
    root = repo(tmp_path)
    seen = {}

    async def spy(info, summary, authors):
        seen["authors"] = authors
        return {"approve": True, "problems": [], "reasons": [], "reviewer": "upstage"}

    j, t, dl = reviewed_loop(tmp_path, root, spy, kind="conversation")
    change(root)
    asyncio.run(dl.release("set VALUE to 9", PLAN))
    assert seen["authors"] == ["gemini"]  # the brain that answered in the task is passed as the author
    assert "gemini" not in reviewers(FamilyRouter(), seen["authors"])
    assert reviewers(FamilyRouter(), ["groq"]) == ["openrouter", "gemini"]  # nor the author's model on another provider
