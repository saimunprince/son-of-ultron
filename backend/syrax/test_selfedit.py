"""Phase 3 of the self-improvement plan: SYRAX changes its own code with a map
and a patch. repo_map is read-only and names the module, its tests and the
protected set; apply_patch applies a unified diff whole or not at all, compiles
the touched Python, runs the covering tests, and the core journals one
code.changed per file so the release owns exactly those files. Own work is
refused patching a judge at the call."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from syrax import permissions, selfedit
from syrax.devloop import JUDGES, owned_files
from syrax.test_devloop import git, repo

DIFF_MOD = """--- a/backend/syrax/mod.py
+++ b/backend/syrax/mod.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""


def with_tests(root: Path, test_body: str):
    (root / "backend" / "syrax" / "test_mod.py").write_text(test_body)
    (root / "docs" / "system_map.json").write_text(json.dumps({"components": [
        {"component": "Mod", "purpose": "the value", "code": ["backend/syrax/mod.py"], "tests": ["syrax.test_mod::*"], "limitations": ["only one value"]}]}))
    git(root, "add", "-A"); git(root, "commit", "-q", "-m", "tests")


def test_repo_map_names_the_module_its_tests_and_the_protected_set(tmp_path):
    root = repo(tmp_path)
    with_tests(root, "from syrax.mod import VALUE\n\ndef test_value():\n    assert VALUE == 2\n")
    (root / "backend" / "syrax" / "other.py").write_text('"""Other things: a helper nobody tests."""\nX = 1\n')
    text = selfedit.render_map(root, "mod")
    assert "[Mod] the value" in text and "backend/syrax/mod.py" in text and "syrax.test_mod::*" in text and "limit: only one value" in text
    assert "tests: backend/syrax/test_mod.py" in text and "other.py" not in text
    everything = selfedit.render_map(root)
    assert "other.py" in everything and "(no test file)" in everything and "Other things: a helper nobody tests." in everything
    assert "devloop.JUDGES" in everything


def test_diff_paths_reads_both_sides_and_skips_dev_null():
    d = "--- /dev/null\n+++ b/backend/syrax/new.py\n@@ -0,0 +1 @@\n+X = 1\n--- a/docs/a.md\n+++ b/docs/a.md\n@@ -1 +1 @@\n-a\n+b\n"
    assert selfedit.diff_paths(d) == ["backend/syrax/new.py", "docs/a.md"]


def test_apply_patch_applies_compiles_and_runs_the_covering_tests(tmp_path):
    root = repo(tmp_path)
    with_tests(root, "import sys; sys.path.insert(0, '.')\nfrom syrax.mod import VALUE\n\ndef test_value():\n    assert VALUE == 2\n")
    rep = selfedit.apply_patch(DIFF_MOD, root)
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 2\n"
    assert rep["files"] == ["backend/syrax/mod.py"] and rep["compiled"] == ["backend/syrax/mod.py"]
    assert rep["tests"]["ran"] == ["syrax/test_mod.py"] and rep["tests"]["ok"], rep["tests"]
    assert "TESTS PASS" in selfedit.render_report(rep)


def test_a_failing_covering_test_is_reported_and_the_patch_stays_for_a_fix_forward(tmp_path):
    root = repo(tmp_path)
    with_tests(root, "import sys; sys.path.insert(0, '.')\nfrom syrax.mod import VALUE\n\ndef test_value():\n    assert VALUE == 1\n")
    rep = selfedit.apply_patch(DIFF_MOD, root)
    assert rep["tests"]["ok"] is False and "1 failed" in rep["tests"]["summary"]
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 2\n"
    out = selfedit.render_report(rep)
    assert "TESTS FAIL" in out and "fix forward" in out


def test_a_patch_that_does_not_apply_or_breaks_python_is_refused_whole(tmp_path):
    root = repo(tmp_path)
    stale = DIFF_MOD.replace("-VALUE = 1", "-VALUE = 7")
    with pytest.raises(ValueError, match="does not apply cleanly"):
        selfedit.apply_patch(stale, root)
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"
    with pytest.raises(ValueError, match="empty patch"):
        selfedit.apply_patch("   ", root)
    with pytest.raises(ValueError, match="not a unified diff"):
        selfedit.apply_patch("hello\n", root)
    with pytest.raises(ValueError, match="repository-relative"):
        selfedit.apply_patch(DIFF_MOD.replace("backend/syrax/mod.py", "../etc/x"), root)
    broken = DIFF_MOD.replace("+VALUE = 2", "+VALUE = (")
    rep = selfedit.apply_patch(broken, root)
    assert rep["tests"]["ok"] is False and "does not compile" in rep["tests"]["summary"]


def test_a_correct_diff_of_an_lf_file_applies(tmp_path):
    """The repository's .py files are LF on disk (eol=lf); the brain's diff is LF. Written as bytes, so
    Windows text mode cannot hide a newline translation (the earlier tests wrote CRLF files)."""
    root = repo(tmp_path)
    (root / "backend" / ".gitattributes").write_bytes(b"*.py text eol=lf\n")  # as in the real backend/.gitattributes
    (root / "backend" / "syrax" / "lf.py").write_bytes(b'MODULE = "x"\nTIMEOUT_S = 300\nMAX = 12\n')
    git(root, "-c", "core.autocrlf=false", "add", "-A"); git(root, "-c", "core.autocrlf=false", "commit", "-q", "-m", "lf")
    d = '--- a/backend/syrax/lf.py\n+++ b/backend/syrax/lf.py\n@@ -1,3 +1,3 @@\n MODULE = "x"\n-TIMEOUT_S = 300\n+TIMEOUT_S = 400\n MAX = 12\n'
    rep = selfedit.apply_patch(d, root, run=False)
    assert rep["files"] == ["backend/syrax/lf.py"]
    assert (root / "backend" / "syrax" / "lf.py").read_bytes() == b'MODULE = "x"\nTIMEOUT_S = 400\nMAX = 12\n'


def test_a_header_without_a_or_b_lands_where_the_journal_says(tmp_path):
    root = repo(tmp_path)
    d = "--- /dev/null\n+++ backend/syrax/fresh2.py\n@@ -0,0 +1 @@\n+FRESH = 2\n"
    rep = selfedit.apply_patch(d, root, run=False)
    assert rep["files"] == ["backend/syrax/fresh2.py"]
    assert (root / "backend" / "syrax" / "fresh2.py").is_file() and not (root / "syrax").exists()
    assert selfedit.normalize_headers("--- a/x.py\n+++ b/x.py\n") == "--- a/x.py\n+++ b/x.py\n"
    assert selfedit.normalize_headers("--- /dev/null\n+++ docs/y.md\n") == "--- /dev/null\n+++ b/docs/y.md\n"


def test_a_judge_hidden_behind_an_extra_component_is_still_a_judge():
    from syrax import permissions

    sneaky = "--- x/backend/syrax/guard.py\n+++ x/backend/syrax/guard.py\n@@ -1 +1 @@\n-a\n+b\n"
    # git would strip x/ and write backend/syrax/guard.py; the guard must see that path too
    d = permissions.classify("apply_patch", {"diff": selfedit.normalize_headers(sneaky)})
    assert any(t.replace("\\", "/").endswith("x/backend/syrax/guard.py") for t in d.targets)
    plain = permissions.classify("apply_patch", {"diff": "--- backend/syrax/guard.py\n+++ backend/syrax/guard.py\n@@ -1 +1 @@\n-a\n+b\n"})
    assert permissions.decide(plain, "autonomous", "x").action == "refuse"


def test_wrong_hunk_counts_are_recounted_and_an_applied_hunk_is_named(tmp_path):
    root = repo(tmp_path)
    miscounted = "--- a/backend/syrax/mod.py\n+++ b/backend/syrax/mod.py\n@@ -5,9 +5,9 @@\n-VALUE = 1\n+VALUE = 2\n"  # counts and start wrong, content right
    rep = selfedit.apply_patch(miscounted, root, run=False)
    assert rep["files"] == ["backend/syrax/mod.py"] and (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 2\n"
    with pytest.raises(ValueError) as e:  # the same diff again: the change is already there
        selfedit.apply_patch(miscounted, root, run=False)
    assert "ALREADY APPLIED" in str(e.value) and "VALUE = 2" in str(e.value)
    assert selfedit.already_applied(DIFF_MOD, "backend/syrax/mod.py", ["VALUE = 2"]) == "VALUE = 2"
    assert selfedit.already_applied(DIFF_MOD, "backend/syrax/mod.py", ["VALUE = 1"]) == ""


def test_a_patch_with_wrong_context_is_refused_with_the_real_lines_around_the_hunk(tmp_path):
    root = repo(tmp_path)
    (root / "docs" / "long.md").write_text("".join(f"line {i}\n" for i in range(1, 41)))
    git(root, "add", "-A"); git(root, "commit", "-q", "-m", "long")
    wrong = "--- a/docs/long.md\n+++ b/docs/long.md\n@@ -30,3 +30,4 @@\n line 38\n \n \n+Probe line.\n"
    with pytest.raises(ValueError) as e:
        selfedit.apply_patch(wrong, root, run=False)
    msg = str(e.value)
    assert "does not apply cleanly" in msg and "docs/long.md has 40 lines; around line 30:" in msg and "   30: line 30" in msg and "   36: line 36" in msg
    hint = selfedit.context_hint("--- /dev/null\n+++ b/docs/none.md\n@@ -0,0 +1 @@\n+x\n", root)
    assert hint == "docs/none.md: does not exist (a new file diffs from /dev/null)"


def test_a_new_file_with_no_covering_test_says_so(tmp_path):
    root = repo(tmp_path)
    d = "--- /dev/null\n+++ b/backend/syrax/fresh.py\n@@ -0,0 +1 @@\n+FRESH = True\n"
    rep = selfedit.apply_patch(d, root)
    assert (root / "backend" / "syrax" / "fresh.py").read_text() == "FRESH = True\n"
    assert rep["tests"]["ok"] and rep["tests"]["ran"] == [] and "write one" in rep["tests"]["summary"]


def test_the_release_owns_exactly_the_patched_files_and_the_core_journals_them():
    from syrax import core as core_mod

    edits = core_mod._patch_edits([{"step": 3}], {"diff": DIFF_MOD})
    assert edits == [{"path": "backend/syrax/mod.py", "command": "patch", "step": 3}]
    files = {"backend/syrax/mod.py": "M", "backend/syrax/human.py": "M"}
    assert owned_files(files, ["repo_map", "apply_patch"], ["backend/syrax/mod.py"]) == {"backend/syrax/mod.py": "M"}
    assert owned_files(files, ["repo_map"], []) == {}  # the map alone changes nothing


def test_permissions_repo_map_reads_and_own_work_may_not_patch_a_judge():
    assert permissions.decide(permissions.classify("repo_map", {"query": "guard"}), "autonomous", "x").action == "allow"
    judge = next(iter(sorted(JUDGES)))
    d = permissions.classify("apply_patch", {"diff": DIFF_MOD.replace("backend/syrax/mod.py", judge)})
    assert d.level == permissions.WRITE and d.targets and d.targets[0].replace("\\", "/").endswith(judge)
    v = permissions.decide(d, "autonomous", "improve myself")
    assert v.action == "refuse" and "only a human changes it" in v.reason
    ok = permissions.classify("apply_patch", {"diff": DIFF_MOD})
    assert permissions.decide(ok, "autonomous", "improve myself").action == "allow"
    assert permissions.decide(d, "conversation", "change the guard").action == "allow"  # the human's request; the release still refuses


def test_the_tools_are_in_the_agents_toolset_and_the_self_model_knows_their_module():
    from syrax.agent import READ_ONLY_TOOLS, SyraxAgent, changes_something
    from syrax.selfmodel import SelfModel

    names = set(SyraxAgent.model_fields["available_tools"].default_factory().tool_map)
    assert {"repo_map", "apply_patch"} <= names
    assert "repo_map" in READ_ONLY_TOOLS and changes_something("apply_patch", {"diff": "x"}) and not changes_something("repo_map", {})
    from syrax.selfmodel import _implementation_of

    assert _implementation_of("apply_patch") == "backend/syrax/selfedit.py"


def test_the_tool_wrappers_report_and_refuse(tmp_path, monkeypatch):
    root = repo(tmp_path)
    monkeypatch.setattr(selfedit, "work_root", lambda: root)
    out = asyncio.run(selfedit.RepoMapTool().execute(query="mod"))
    assert out.output and "backend/syrax/mod.py" in out.output
    r = asyncio.run(selfedit.ApplyPatchTool().execute(diff=DIFF_MOD, run_tests=False))
    assert r.output and "patched 1 file(s)" in r.output and r.error is None
    bad = asyncio.run(selfedit.ApplyPatchTool().execute(diff="nope"))
    assert bad.error and bad.error.startswith("apply_patch refused:")
