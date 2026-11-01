"""The owner's approve-from-chat path (2026-11-01): a conversation release held at review (no second brain, or a
rejection) lands when the human's own next message approves it and the working tree holds exactly the change that
was shown. A changed diff, an old hold, the brain's words or a long message that only mentions approval do not."""

import asyncio

from syrax import devloop
from syrax.devloop import DevLoop
from syrax.journal import Journal
from syrax.test_devloop import PASS, git, repo
from syrax.test_review_unavailable import PLAN, nobody, reject


def held(tmp_path, reviewer=nobody):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("set VALUE to 9", kind="conversation")
    j.record_sync("brain.answered", {"provider": "gemini"}, task_id=t)
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    dl.reviewer = reviewer
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 9\n")
    rep = asyncio.run(dl.release("set VALUE to 9", PLAN))
    assert rep.get("held"), rep
    return root, j, dl


def ask(j, dl, words):
    t = j.start_task_sync(words, kind="conversation")
    j.record_sync("brain.answered", {"provider": "gemini"}, task_id=t)
    dl.task_id_provider = lambda: t
    return asyncio.run(dl.release("set VALUE to 9", PLAN)), t


def test_the_humans_approval_lands_the_held_change(tmp_path):
    for i, reviewer in enumerate((nobody, reject)):
        root, j, dl = held(tmp_path / str(i), reviewer)
        rep, t = ask(j, dl, "approve, land it")
        assert rep["outcome"] == "COMMITTED", rep
        assert git(root, "log", "-1", "--format=%s") == "syrax: set VALUE to 9"
        ev = [e["payload"] for e in j.events(t) if e["type"] == "release.approved_by_human"]
        assert ev and ev[0]["words"] == "approve, land it" and ev[0]["diff_sha256"]


def test_a_changed_diff_is_not_covered_by_the_approval(tmp_path):
    root, j, dl = held(tmp_path)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 10\n")
    rep, _ = ask(j, dl, "approve koro")
    assert rep.get("held") and rep["outcome"] == "REVIEW_UNAVAILABLE"


def test_words_that_are_not_a_short_approval_do_not_land_it(tmp_path):
    root, j, dl = held(tmp_path)
    for words in ("why was it held?", "please explain the review " + "and more " * 30 + "approve"):
        rep, _ = ask(j, dl, words)
        assert rep.get("held"), words
    head = git(root, "rev-parse", "HEAD")
    assert git(root, "log", "-1", "--format=%s") == "init" and head


def test_approval_words_are_recognised():
    for w in ("approve", "approved", "land it", "commit it", "go ahead", "approve koro", "land kore dao", "অনুমোদন দিলাম"):
        assert devloop.APPROVAL.search(w), w
    for w in ("what did the reviewer say", "show me the diff", "reject it"):
        assert not devloop.APPROVAL.search(w), w


def test_an_old_hold_is_not_approved(tmp_path, monkeypatch):
    root, j, dl = held(tmp_path)
    monkeypatch.setattr(devloop, "APPROVAL_WINDOW_S", -1)  # the hold is older than the window
    rep, _ = ask(j, dl, "approve")
    assert rep.get("held")


def test_the_held_report_tells_the_human_how_to_approve(tmp_path):
    root, j, dl = held(tmp_path)
    rep, _ = ask(j, dl, "why")
    assert "approve" in devloop.render(rep).lower()
