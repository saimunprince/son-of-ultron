"""Audit 2026-11-01 (F17): a rollback snapshot held each new file as plain text after "# untracked: <path>", so
`git apply` of the snapshot restored the edits but never the new files. New files are /dev/null diffs now."""

from syrax.devloop import DevLoop, _git
from syrax.journal import Journal
from syrax.test_devloop import PASS, git, repo


def test_applying_a_snapshot_brings_back_edits_and_new_files(tmp_path):
    root = repo(tmp_path)
    (root / "docs" / "notes.md").write_text("one\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "notes")
    (root / "docs" / "notes.md").write_text("one\ntwo\n")
    (root / "docs" / "brand_new.md").write_text("fresh\nlines\n")
    dl = DevLoop(Journal(tmp_path / "j.db"), root=root, gates=lambda: PASS)
    info = {"head": git(root, "rev-parse", "HEAD"), "diff": _git(["diff"], root).stdout, "untracked": ["docs/brand_new.md"]}
    snap = dl.snapshot(info)
    git(root, "checkout", "--", "docs/notes.md")
    (root / "docs" / "brand_new.md").unlink()
    git(root, "apply", str(snap))
    assert (root / "docs" / "notes.md").read_text() == "one\ntwo\n"
    assert (root / "docs" / "brand_new.md").read_text() == "fresh\nlines\n"
