"""Live 2026-10-13: the daily ledger (docs only) was gated GREEN and committed in
its worktree, but a human's code commit moved the running tree meanwhile and the
fast-forward failed, so nothing was published. A docs-only commit whose files
nobody else touched since its base is replayed onto the moved branch and lands;
a code change, or a document someone else changed, still does not."""

import asyncio

from syrax.test_devloop import git
from syrax.test_isolated_evolution import PLAN, isolated


def human_commit(root, rel, text):
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "human")
    return git(root, "rev-parse", "HEAD")


def test_a_docs_only_commit_lands_on_a_moved_branch_when_nobody_touched_its_files(tmp_path):
    root, j, t, dl, wt = isolated(tmp_path)
    human = human_commit(root, "backend/syrax/mod.py", "VALUE = 7\n")
    (wt / "docs").mkdir(exist_ok=True)  # the test repo's docs/ folder is empty, so a checkout has none
    (wt / "docs" / "RISE.md").write_text("# SYRAX rise ledger\n")
    rep = asyncio.run(dl.release("docs(rise): the ledger", PLAN))
    assert rep["outcome"] == "COMMITTED", rep
    assert git(root, "rev-parse", "HEAD") == rep["commit"] and git(root, "rev-parse", "HEAD^") == human
    assert (root / "docs" / "RISE.md").read_text() == "# SYRAX rise ledger\n" and (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 7\n"
    assert git(root, "status", "--porcelain") == ""


def test_a_document_someone_else_changed_does_not_land(tmp_path):
    root, j, t, dl, wt = isolated(tmp_path)
    human = human_commit(root, "docs/RISE.md", "# a human's ledger\n")
    (wt / "docs").mkdir(exist_ok=True)  # the test repo's docs/ folder is empty, so a checkout has none
    (wt / "docs" / "RISE.md").write_text("# SYRAX rise ledger\n")
    rep = asyncio.run(dl.release("docs(rise): the ledger", PLAN))
    assert rep["outcome"] == "COMMIT_FAILED" and "could not fast-forward the running tree" in rep["error"]
    assert git(root, "rev-parse", "HEAD") == human and (root / "docs" / "RISE.md").read_text() == "# a human's ledger\n"


def test_a_code_change_still_never_lands_on_a_moved_branch(tmp_path):
    root, j, t, dl, wt = isolated(tmp_path)
    human = human_commit(root, "docs/notes.md", "notes\n")
    (wt / "backend" / "syrax" / "mod.py").write_text("VALUE = 5\n")
    (wt / "docs").mkdir(exist_ok=True)  # the test repo's docs/ folder is empty, so a checkout has none
    (wt / "docs" / "RISE.md").write_text("# ledger\n")
    rep = asyncio.run(dl.release("code and docs", PLAN))
    assert rep["outcome"] == "COMMIT_FAILED"
    assert git(root, "rev-parse", "HEAD") == human and (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"
