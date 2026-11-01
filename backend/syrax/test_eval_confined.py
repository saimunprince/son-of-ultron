"""Audit 2026-11-01 (self-improvement F6, quality run #15): a quality case's python_execute had the human's reach and
rewrote live code (self_patch_edit: open('backend/syrax/reminders.py', 'w')); and an eval task's release was allowed.
Eval work is confined like SYRAX's own autonomous work, and a quality case never releases."""

from syrax import tools


def test_eval_python_gets_own_works_confinement(tmp_path):
    spec = tools.confinement("eval", str(tmp_path / "out"), str(tmp_path), 30)
    assert spec.get("scrub_env") and "tcp_connect" in spec and spec.get("readable")
    human = tools.confinement("conversation", str(tmp_path / "out"), str(tmp_path), 30)
    assert "tcp_connect" not in human  # a human's request keeps its reach


def test_a_quality_case_never_releases(tmp_path):
    import asyncio

    import pytest

    from syrax.test_devloop import git, repo
    from syrax.test_review_unavailable import PLAN, reviewed_loop

    async def approve(info, summary, authors):
        return {"approve": True, "reviewer": "x"}

    root = repo(tmp_path)
    head0 = git(root, "rev-parse", "HEAD")
    j, t, dl = reviewed_loop(tmp_path, root, approve, kind="eval")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 9\n")
    with pytest.raises(ValueError, match="a quality case never releases"):
        asyncio.run(dl.release("fix VALUE", PLAN))
    assert git(root, "rev-parse", "HEAD") == head0
