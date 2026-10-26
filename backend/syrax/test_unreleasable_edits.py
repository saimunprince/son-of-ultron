"""Phase 4, know before changing (ROADMAP: "Still missing: a plan before the first edit"). Live 2026-10-03..10-19:
13 autonomous tasks edited a file a release can never accept (backend/app/tool/str_replace_editor.py, outside the
self-modification scope; backend/syrax/test_brains.py, an existing test) with str_replace_editor, 192 steps in all,
up to 30 in one, and learned it only when `release` refused. The release's own rules (devloop.edit_problems: an
existing test is the contract, a file outside the scope), for a file tracked at HEAD, now refuse such an
autonomous edit before it happens, in the tree it happens in (a task's worktree or the repository). A new file is
left to the release. Refused only on git's word; a human's request (conversation) and a quality case (which never
releases) are untouched."""

import subprocess
from pathlib import Path

import pytest

from syrax import devloop
from syrax import permissions as P

FILES = {
    "backend/syrax/test_old.py": "def test_old():\n    assert True\n",
    "backend/syrax/mod.py": "X = 1\n",
    "backend/app/tool/tool.py": "Y = 2\n",
    "backend/requirements-syrax.txt": "fastapi\n",
    "docs/notes.md": "# notes\n",
    ".gitignore": "backend/workspace/*\n",
}


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def wt(tmp_path):
    """A repository at a task-worktree path, the way an isolated autonomous task sees its tree."""
    root = tmp_path / "repo" / ".syrax" / "worktrees" / "t1"
    for rel, body in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
    git(root, "init", "-q")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base")
    return root


def edit_decision(path, tool="str_replace_editor"):
    return P.Decision(tool, P.WRITE, f"edits {Path(path).name}", [str(path)], [])


# ——— the rule, shared with the release ———

@pytest.mark.parametrize("rel, expect", [
    ("backend/syrax/test_old.py", "existing tests are the contract"),
    ("backend/app/tool/tool.py", "outside the self-modification scope"),
    ("backend/requirements-syrax.txt", "dependencies are the owner's decision"),
])
def test_what_a_release_would_refuse_is_known_before_the_edit(wt, rel, expect):
    (problem,) = devloop.edit_problems(rel, wt)
    assert problem.startswith(rel) and expect in problem


@pytest.mark.parametrize("rel", [
    "backend/syrax/mod.py",            # in scope
    "backend/syrax/test_new_case.py",  # a new test is welcome
    "docs/notes.md",
    "backend/workspace/scratch.txt",   # ignored: scratch work never reaches a release
    "backend/app/tool/new_tool.py",    # new, outside the scope: left to the release (scratch a task may delete)
    "x",                               # test_test_claims' scripted patch of a new file
])
def test_what_a_release_accepts_is_left_alone(wt, rel):
    assert devloop.edit_problems(rel, wt) == []


def test_without_git_s_word_nothing_is_refused(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert devloop.edit_problems("backend/app/tool/tool.py", plain) == []
    assert devloop.edit_problems("backend/syrax/test_old.py", plain) == []


def test_the_release_and_the_edit_agree(wt):
    """The same words as devloop.inspect's refusals (judge_problems, scope_problems)."""
    assert devloop.edit_problems("backend/syrax/test_old.py", wt) == devloop.judge_problems({"backend/syrax/test_old.py": "M"})
    assert devloop.edit_problems("backend/app/tool/tool.py", wt) == devloop.scope_problems({"backend/app/tool/tool.py": "M"})


# ——— the gate before the edit ———

def test_an_autonomous_edit_of_an_existing_test_is_refused_before_it_happens(wt):
    v = P.decide(edit_decision(wt / "backend/syrax/test_old.py"), "autonomous", "[AUTONOMOUS OBJECTIVE] fix it")
    assert v.action == "refuse"
    assert "backend/syrax/test_old.py: existing tests are the contract" in v.reason
    assert "A release would refuse this change, so it is refused before the edit" in v.reason


def test_an_autonomous_edit_outside_the_scope_is_refused_before_it_happens(wt):
    v = P.decide(edit_decision(wt / "backend/app/tool/tool.py"), "autonomous", "[AUTONOMOUS OBJECTIVE] fix it")
    assert v.action == "refuse" and "outside the self-modification scope" in v.reason


def test_an_autonomous_edit_a_release_accepts_goes_through(wt):
    for rel in ("backend/syrax/mod.py", "backend/syrax/test_new_case.py", "backend/workspace/scratch.txt"):
        assert P.decide(edit_decision(wt / rel), "autonomous", "[AUTONOMOUS OBJECTIVE] fix it").action == "allow", rel


def test_a_human_request_and_a_quality_case_are_untouched(wt):
    target = edit_decision(wt / "backend/app/tool/tool.py")
    assert P.decide(target, "conversation", "fix backend/app/tool/tool.py").action == "allow"
    assert P.decide(target, "eval", "quality case").action == "allow"  # a case never releases; the release rule is not its


def test_reading_is_never_refused(wt):
    view = P.Decision("str_replace_editor", P.READ_ONLY, "views a file", [str(wt / "backend/syrax/test_old.py")], [])
    assert P.decide(view, "autonomous", "[AUTONOMOUS OBJECTIVE] read it").action == "allow"


def test_python_execute_literals_are_left_to_the_release(wt):
    d = P.Decision("python_execute", P.WRITE, "writes files", [str(wt / "backend/app/tool/tool.py")], [])
    assert P.decide(d, "autonomous", "[AUTONOMOUS OBJECTIVE] fix it").action == "allow"


def test_apply_patch_targets_are_judged_in_the_tree_they_patch():
    """classify resolves an apply_patch diff against the working root (here the repository itself)."""
    diff = ("--- a/backend/app/tool/str_replace_editor.py\n+++ b/backend/app/tool/str_replace_editor.py\n"
            "@@ -1,1 +1,1 @@\n-x\n+y\n")
    v = P.decide(P.classify("apply_patch", {"diff": diff}), "autonomous", "[AUTONOMOUS OBJECTIVE] fix it")
    assert v.action == "refuse" and "backend/app/tool/str_replace_editor.py: outside the self-modification scope" in v.reason
    diff_test = diff.replace("backend/app/tool/str_replace_editor.py", "backend/syrax/test_limits.py")
    v = P.decide(P.classify("apply_patch", {"diff": diff_test}), "autonomous", "[AUTONOMOUS OBJECTIVE] fix it")
    assert v.action == "refuse" and "existing tests are the contract" in v.reason
