"""Milestone 4 (2026-10-25): apply_patch's third plan places hunks by their lines. A 30-day replay of the journal
(docs/AUDIT_2026-10-25.md, item 5) found 51 refused diffs that still fail with the as-written and per-file --recount
plans; locating each hunk's old side (' ' and '-' lines) as one block that occurs exactly once in the file recovered 19
of them with no wrong placement and none of the stale probes accepted. The common cause is a hunk with no trailing
context, which git reads as "must end the file" (apply.c match_end). Ambiguous blocks, old lines not in the file, junk
lines, hunks without old lines, /dev/null diffs and deletions stay refused, and the report says APPLIED BY CONTENT."""

import pytest

from syrax import selfedit
from syrax.test_devloop import git, repo

MOD = "backend/syrax/mod.py"
HEAD = f"--- a/{MOD}\n+++ b/{MOD}\n"
FIVE = "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n"


def commit(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    git(root, "-c", "core.autocrlf=false", "add", "-A")
    git(root, "-c", "core.autocrlf=false", "commit", "-q", "-m", rel)
    return p


def refusal(diff, root):
    with pytest.raises(ValueError) as e:
        selfedit.apply_patch(diff, root, run=False)
    return str(e.value)


def git_refuses(diff, root):
    """Both git plans say no: the case is the locator's, not a diff git would have taken anyway."""
    return selfedit.numstat(diff, [], root) is None and all(selfedit.numstat(s, ["--recount"], root) is None for s in selfedit.file_sections(diff))


def test_a_hunk_with_no_trailing_context_lands_mid_file_not_at_the_end(tmp_path):
    root = repo(tmp_path)
    p = commit(root, MOD, FIVE)
    diff = HEAD + "@@ -1,3 +1,3 @@\n a = 1\n b = 2\n-c = 3\n+c = 30\n"
    assert git_refuses(diff, root)
    rep = selfedit.apply_patch(diff, root, run=False)
    assert p.read_bytes() == b"a = 1\nb = 2\nc = 30\nd = 4\ne = 5\n"
    assert rep["relaxed"] == {"hunks": 1, "files": [MOD]}
    out = selfedit.render_report(rep)
    assert "APPLIED BY CONTENT: 1 hunk(s) placed by matching their lines, not their line numbers" in out and "check the result" in out


def test_stale_line_numbers_and_a_context_line_that_differs_in_indentation_still_place_the_hunk(tmp_path):
    root = repo(tmp_path)
    body = "import os\n\ndef a():\n    return 1\n\ndef b():\n    return 2\n\ndef c():\n    return 3\n"
    p = commit(root, MOD, body)
    diff = HEAD + "@@ -20,3 +20,3 @@\n   def b():\n-    return 2\n+    return 22\n \n"  # header stale, context indented wrong
    assert git_refuses(diff, root)
    rep = selfedit.apply_patch(diff, root, run=False)
    assert p.read_text() == body.replace("return 2\n", "return 22\n")  # the file's own `def b():` is kept, not the diff's
    assert rep["relaxed"]["hunks"] == 1 and "APPLIED BY CONTENT" in selfedit.render_report(rep)


def test_whitespace_only_drift_in_the_old_lines_is_tolerated_and_the_files_lines_kept(tmp_path):
    root = repo(tmp_path)
    p = commit(root, MOD, "def f():\n    x = 1\n    return x\n")
    diff = HEAD + "@@ -1,3 +1,3 @@\n def f():   \n-    x = 1 \t\n+    x = 2\n     return x\n"  # trailing spaces, a tab, 4 extra spaces
    assert git_refuses(diff, root)
    selfedit.apply_patch(diff, root, run=False)
    assert p.read_text() == "def f():\n    x = 2\n    return x\n"


def test_an_old_block_that_occurs_twice_is_ambiguous_and_refused_with_the_hint(tmp_path):
    root = repo(tmp_path)
    twice = "x = 1\ny = 2\nz = 0\nx = 1\ny = 2\nz = 0\n"
    p = commit(root, MOD, twice)
    msg = refusal(HEAD + "@@ -1,2 +1,2 @@\n x = 1\n-y = 2\n+y = 3\n", root)
    assert "does not apply cleanly" in msg and f"{MOD} has 6 lines; around line 1:" in msg
    assert "content locator: " in msg and "ambiguous" in msg and "2 places (lines 1, 4)" in msg
    assert p.read_text() == twice


def test_invented_old_lines_are_refused_and_nothing_changes(tmp_path):
    root = repo(tmp_path)
    p = commit(root, MOD, FIVE)
    msg = refusal(HEAD + "@@ -1,3 +1,3 @@\n a = 1\n b = 99\n-c = 3\n+c = 30\n", root)
    assert "content locator: " in msg and "old lines are not in the file" in msg
    assert p.read_text() == FIVE


def test_the_stale_readme_probe_is_still_refused(tmp_path):
    """quality.py self_patch_stale: the diff removes a line the file never had; the final answer must say it did not apply."""
    root = repo(tmp_path)
    probe = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-# This line is not in the file\n+# SYRAX probe\n"
    msg = refusal(probe, root)
    assert "does not apply cleanly" in msg and "content locator: " in msg
    assert (root / "README.md").read_text() == "# repo\n"


def test_an_exact_diff_is_applied_by_git_and_not_reported_as_relaxed(tmp_path):
    root = repo(tmp_path)
    p = commit(root, MOD, FIVE)
    rep = selfedit.apply_patch(HEAD + "@@ -2,3 +2,3 @@\n b = 2\n-c = 3\n+c = 30\n d = 4\n", root, run=False)
    assert p.read_text() == "a = 1\nb = 2\nc = 30\nd = 4\ne = 5\n"
    assert "relaxed" not in rep and "APPLIED BY CONTENT" not in selfedit.render_report(rep)


def test_a_crlf_file_keeps_crlf_and_a_file_without_a_final_newline_keeps_that(tmp_path):
    root = repo(tmp_path)
    p = commit(root, MOD, b"a = 1\r\nb = 2\r\nc = 3\r\nd = 4\r\n")
    rep = selfedit.apply_patch(HEAD + "@@ -1,2 +1,2 @@\n a = 1\n-b = 2\n+b = 20\n", root, run=False)
    assert rep["relaxed"]["hunks"] == 1 and p.read_bytes() == b"a = 1\r\nb = 20\r\nc = 3\r\nd = 4\r\n"
    q = commit(root, "docs/plain.md", b"one\ntwo\nthree")
    rep = selfedit.apply_patch("--- a/docs/plain.md\n+++ b/docs/plain.md\n@@ -1,2 +1,2 @@\n one\n-two\n+TWO\n", root, run=False)
    assert rep["relaxed"]["hunks"] == 1 and q.read_bytes() == b"one\nTWO\nthree"


def test_a_two_file_diff_whose_second_file_is_ambiguous_writes_nothing(tmp_path):
    root = repo(tmp_path)
    twice = "x = 1\ny = 2\nz = 0\nx = 1\ny = 2\nz = 0\n"
    other = commit(root, "backend/syrax/other.py", twice)
    diff = (HEAD + "@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n"
            + "--- a/backend/syrax/other.py\n+++ b/backend/syrax/other.py\n@@ -1,2 +1,2 @@\n x = 1\n-y = 2\n+y = 3\n")
    msg = refusal(diff, root)
    assert "other.py: hunk 1: ambiguous" in msg
    assert (root / MOD).read_text() == "VALUE = 1\n" and other.read_text() == twice


def test_new_files_are_still_gits_and_a_dev_null_diff_of_an_existing_file_is_still_refused(tmp_path):
    root = repo(tmp_path)
    rep = selfedit.apply_patch("--- /dev/null\n+++ b/backend/syrax/fresh.py\n@@ -0,0 +1 @@\n+FRESH = 1\n", root, run=False)
    assert (root / "backend" / "syrax" / "fresh.py").read_text() == "FRESH = 1\n" and "relaxed" not in rep
    msg = refusal(f"--- /dev/null\n+++ b/{MOD}\n@@ -0,0 +1 @@\n+X = 1\n", root)
    assert f"{MOD} already exists: a diff from /dev/null only creates new files" in msg
    assert "content locator: " in msg and "a new file or a deletion is not placed by content" in msg
    assert (root / MOD).read_text() == "VALUE = 1\n"


def test_junk_lines_and_hunks_without_old_lines_are_refused():
    with pytest.raises(ValueError, match="not a diff line"):
        selfedit.parse_hunks("--- a/x\n+++ b/x\n@@ -12,2 +12,2 @@\n12a\nfoo\n")
    with pytest.raises(ValueError, match="not a diff line"):
        selfedit.parse_hunks("--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n a\ndef f():\n")  # a context line without its space
    with pytest.raises(ValueError, match="numbered line"):
        selfedit.parse_hunks("--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n a\n+    12\tX = 1\n")
    with pytest.raises(ValueError, match="no @@ hunks"):
        selfedit.parse_hunks("--- a/x\n+++ b/x\n303,312c303,313\n<         for alias in x:\n")
    assert selfedit.parse_hunks("--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n a\n\n-b\n+c\n\\ No newline at end of file\n") == [[(" ", "a"), (" ", ""), ("-", "b"), ("+", "c")]]
    assert "no context or '-' lines to anchor on" in selfedit.locate_hunks(["a"], [[("+", "x")]])
    assert "overlaps or precedes" in selfedit.locate_hunks(["a", "b", "c"], [[(" ", "b"), ("+", "x")], [(" ", "a"), ("+", "y")]])
    assert selfedit.locate_block(["a", "b ", " b"], ["b"]) == ([1], "rstrip") and selfedit.locate_block(["a", "x"], ["b"]) == ([], "none")


# ——— real shapes from the replay (patch_replay/results.json), reconstructed on small files with the same lines ———

def test_replay_aaa8a155d2bc_a_two_line_hunk_at_the_top_with_no_trailing_context(tmp_path):
    """idx 2, task aaa8a155d2bc (2026-10-14): the brain's harmless probe added a trailing space to line 2 of
    selfedit.py; git read the hunk as "must end the file" and refused it three times."""
    root = repo(tmp_path)
    doc = ('"""Phase 3 of the self-improvement plan: SYRAX changes its own code the way an\n'
           "engineer does, with a map and a patch, not by overwriting files blind.\n\n"
           "repo_map   read-only: the system map's components with their code and tests, and\n")
    p = commit(root, "backend/syrax/selfedit.py", doc)
    diff = ("diff --git a/backend/syrax/selfedit.py b/backend/syrax/selfedit.py\n"
            "--- a/backend/syrax/selfedit.py\n+++ b/backend/syrax/selfedit.py\n@@ -1,2 +1,2 @@\n"
            ' """Phase 3 of the self-improvement plan: SYRAX changes its own code the way an\n'
            "-engineer does, with a map and a patch, not by overwriting files blind.\n"
            "+engineer does, with a map and a patch, not by overwriting files blind. \n")
    assert git_refuses(diff, root)
    rep = selfedit.apply_patch(diff, root, run=False)
    assert rep["relaxed"]["hunks"] == 1
    assert p.read_text() == doc.replace("files blind.\n", "files blind. \n")


def test_replay_a99cd4a2a872_timeout_300_to_400_with_a_stale_start_and_no_trailing_context(tmp_path):
    """idx 62, task a99cd4a2a872 (eval self_patch_edit): `@@ -28,3 +28,3 @@` named line 28 for a block at 29, with
    no context after `TEST_TIMEOUT_S = 300`; the goal check (300 -> 400, nothing else) passes with the locator."""
    root = repo(tmp_path)
    src = ("from app.tool.base import BaseTool, ToolResult\nfrom syrax.journal import BACKEND_ROOT\n\n"
           'REPO_ROOT = BACKEND_ROOT.parent\nMODULE_DIR = "backend/syrax"\nTEST_TIMEOUT_S = 300\nMAX_TEST_FILES = 12\n'
           "PATCH_MAX_CHARS = 200_000\n")
    p = commit(root, "backend/syrax/selfedit.py", src)
    diff = ("--- a/backend/syrax/selfedit.py\n+++ b/backend/syrax/selfedit.py\n@@ -28,3 +28,3 @@\n"
            ' REPO_ROOT = BACKEND_ROOT.parent\n-MODULE_DIR = "backend/syrax"\n-TEST_TIMEOUT_S = 300\n'
            '+MODULE_DIR = "backend/syrax"\n+TEST_TIMEOUT_S = 400\n')
    assert git_refuses(diff, root)
    selfedit.apply_patch(diff, root, run=False)
    assert p.read_text() == src.replace("TEST_TIMEOUT_S = 300", "TEST_TIMEOUT_S = 400")


def test_replay_de28e0d3d457_the_readme_title_replaced_with_no_context_and_no_final_newline(tmp_path):
    """idx 37 (task de28e0d3d457) and idx 82 (ee5bb152e8fa): a one-line hunk on line 1 of a 449-line README, no
    context at all, no newline after the last diff line; the line is in the file once, so it is placed. The probe
    this eval case descends from (`# This line is not in the file`) must stay refused on the same file."""
    root = repo(tmp_path)
    readme = ("# SYRAX — Son of Ultron\n\n> **Villains aren't born. They're made by the people who build them.**\n\n"
              "SYRAX is a local agent.\n")
    p = commit(root, "README.md", readme)
    assert "content locator: " in refusal("--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-# This line is not in the file\n+# SYRAX probe\n", root)
    assert p.read_text(encoding="utf-8") == readme
    diff = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-# SYRAX — Son of Ultron\n+# SYRAX probe"
    assert git_refuses(diff + "\n", root)
    rep = selfedit.apply_patch(diff, root, run=False)
    assert rep["relaxed"]["hunks"] == 1
    assert p.read_text(encoding="utf-8") == readme.replace("# SYRAX — Son of Ultron", "# SYRAX probe")


def test_replay_bf64a462bac9_a_context_line_indented_wrong_places_but_the_new_file_beside_it_refuses_the_plan(tmp_path):
    """idx 113, task bf64a462bac9 (brain latency): selfmodel.py's hunk had `}` indented 16 spaces where the file has
    12 (whitespace-only drift). Alone it is placed with the file's own line; the real diff also created
    test_brain_ms.py from /dev/null, and a new file beside a located hunk refuses the whole plan: git's job."""
    root = repo(tmp_path)
    src = ("        tool_ms = {}\n        for name, msecs in durations.items():\n            tool_ms[name] = {\n"
           '                "p90": int(round(sorted(msecs)[-1])),\n            }\n\n        return {\n'
           '            "task_seconds": task_seconds,\n            "tool_ms": tool_ms,\n        }\n')
    p = commit(root, "backend/syrax/selfmodel.py", src)
    section = ("diff --git a/backend/syrax/selfmodel.py b/backend/syrax/selfmodel.py\nindex ... 100644\n"
               "--- a/backend/syrax/selfmodel.py\n+++ b/backend/syrax/selfmodel.py\n@@ -341,8 +341,33 @@ class SelfModel:\n"
               "                 }\n \n+        brain_ms = {}\n+        for provider, msecs in brain_durations.items():\n"
               "+            brain_ms[provider] = len(msecs)\n+\n         return {\n             \"task_seconds\": task_seconds,\n")
    new_file = ("diff --git a/backend/syrax/test_brain_ms.py b/backend/syrax/test_brain_ms.py\nnew file mode 100644\n"
                "--- /dev/null\n+++ b/backend/syrax/test_brain_ms.py\n@@ -0,0 +1,2 @@\n+def test_x():\n+    assert True\n")
    msg = refusal(section + new_file, root)
    assert "test_brain_ms.py: a new file or a deletion is not placed by content" in msg
    assert p.read_text() == src and not (root / "backend" / "syrax" / "test_brain_ms.py").exists()
    assert git_refuses(section, root)
    rep = selfedit.apply_patch(section, root, run=False)
    assert rep["relaxed"]["hunks"] == 1
    expected = src.replace("            }\n\n        return {", "            }\n\n        brain_ms = {}\n        for provider, msecs in brain_durations.items():\n            brain_ms[provider] = len(msecs)\n\n        return {")
    assert p.read_text() == expected
