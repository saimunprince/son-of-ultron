"""Quality run #58 (2026-10-22, self_patch_docs): asked to add a line at the end of docs/EXECUTION_PLAN.md, the brain
diffed the existing file from /dev/null and was shown its first lines, then wrote "../docs/EXECUTION_PLAN.md" (a path
from backend/) and was told only that paths must be repository-relative; it answered that the file was out of reach.
apply_patch now names the path it meant and shows the end of a file a /dev/null diff tried to create again."""

import pytest

from syrax import selfedit
from syrax.test_devloop import git, repo

PLAN = "".join(f"step {i}\n" for i in range(1, 21))


def plan_repo(tmp_path):
    root = repo(tmp_path)
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "PLAN.md").write_text(PLAN)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "plan")
    return root


def refusal(diff, root):
    with pytest.raises(ValueError) as e:
        selfedit.apply_patch(diff, root, run=False)
    return str(e.value)


def test_a_path_written_from_backend_is_named_as_the_repository_path(tmp_path):
    root = plan_repo(tmp_path)
    diff = "--- a/../docs/PLAN.md\n+++ b/../docs/PLAN.md\n@@ -20 +20,2 @@\n step 20\n+Probe line.\n"
    msg = refusal(diff, root)
    assert "paths must be repository-relative" in msg and "write it as docs/PLAN.md" in msg
    fixed = diff.replace("../docs/PLAN.md", "docs/PLAN.md")
    selfedit.apply_patch(fixed, root, run=False)
    assert (root / "docs" / "PLAN.md").read_text().endswith("step 20\nProbe line.\n")


def test_an_absolute_path_inside_the_repository_is_named_too(tmp_path):
    root = plan_repo(tmp_path)
    absolute = (root / "docs" / "PLAN.md").as_posix()
    msg = refusal(f"--- a/{absolute}\n+++ b/{absolute}\n@@ -20 +20,2 @@\n step 20\n+Probe line.\n", root)
    assert "write it as docs/PLAN.md" in msg


def test_a_path_that_names_nothing_gets_no_guess(tmp_path):
    root = plan_repo(tmp_path)
    msg = refusal("--- a/../../elsewhere/x/y.md\n+++ b/../../elsewhere/x/y.md\n@@ -1 +1 @@\n-a\n+b\n", root)
    assert "paths must be repository-relative" in msg and "write it as" not in msg


def test_a_diff_from_dev_null_for_an_existing_file_shows_how_it_ends(tmp_path):
    root = plan_repo(tmp_path)
    msg = refusal("--- /dev/null\n+++ b/docs/PLAN.md\n@@ -0,0 +1 @@\n+Probe line.\n", root)
    assert "docs/PLAN.md already exists: a diff from /dev/null only creates new files" in msg
    assert "'--- a/docs/PLAN.md' / '+++ b/docs/PLAN.md'" in msg
    assert "20: step 20" in msg and "1: step 1\n" not in msg
    assert (root / "docs" / "PLAN.md").read_text() == PLAN
