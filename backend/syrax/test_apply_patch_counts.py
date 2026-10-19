"""Objective 291 (2026-10-19): a hunk headed `@@ -303,4 +303,11 @@` carried five old and twelve new lines. git apply
took what the counts covered, ignored the trailing `-return ...` / `+return ...` pair without a word, and apply_patch
answered "patched 1 file(s)"; the release then committed part of the change. When the headers' counts leave lines
out, the patch is applied file by file with --recount, so every line of it lands."""

from syrax import selfedit
from syrax.test_devloop import git, repo

UNDERCOUNTED = """--- a/backend/syrax/mod.py
+++ b/backend/syrax/mod.py
@@ -1,2 +1,3 @@
 VALUE = 1
+EXTRA = 2
 NAME = "a"
-LAST = "old"
+LAST = "new"
"""


def test_lines_past_a_hunks_counts_are_not_dropped(tmp_path):
    root = repo(tmp_path)
    (root / "backend" / "syrax" / "mod.py").write_text('VALUE = 1\nNAME = "a"\nLAST = "old"\n')
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "three lines")
    rep = selfedit.apply_patch(UNDERCOUNTED, root, run=False)
    assert rep["files"] == ["backend/syrax/mod.py"]
    assert (root / "backend" / "syrax" / "mod.py").read_text() == 'VALUE = 1\nEXTRA = 2\nNAME = "a"\nLAST = "new"\n'


def test_a_patch_whose_counts_are_right_applies_as_written(tmp_path):
    root = repo(tmp_path)
    right = "--- a/backend/syrax/mod.py\n+++ b/backend/syrax/mod.py\n@@ -1 +1,2 @@\n-VALUE = 1\n+VALUE = 2\n+X = 3\n"
    assert selfedit.numstat(right, [], root) == (2, 1)
    selfedit.apply_patch(right, root, run=False)
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 2\nX = 3\n"
