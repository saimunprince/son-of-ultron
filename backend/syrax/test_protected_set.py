"""Phase 1, the protected judge: SYRAX may change anything except what measures
it. Every path in the protected set (devloop.JUDGES, which includes its own
definition) is refused in a SYRAX release of any task kind, and own work is
refused writing it at the call; reading it is fine, and normal changes pass."""

import asyncio

import pytest

from syrax import permissions
from syrax.devloop import JUDGES, DevLoop, judge_problems
from syrax.journal import Journal
from syrax.test_devloop import PASS, git, repo

ROOT = permissions.BACKEND_ROOT.parent


def test_the_protected_set_holds_what_judges_and_its_own_definition():
    for must in ("backend/syrax/quality.py", "backend/syrax/verify.py", "backend/syrax/guard.py", "backend/syrax/permissions.py",
                 "backend/syrax/journal.py", "backend/syrax/bench.py", "backend/syrax/codebench.py", "backend/syrax/devloop.py"):
        assert must in JUDGES, must


@pytest.mark.parametrize("path", JUDGES)
def test_every_protected_path_is_refused_in_a_release(path):
    assert any("judges SYRAX's own work" in p for p in judge_problems({path: "M"}))


def test_a_normal_change_passes_and_a_conversation_release_of_a_judge_is_refused(tmp_path):
    assert judge_problems({"backend/syrax/mod.py": "M", "docs/x.md": "M", "backend/syrax/test_new.py": "??"}) == []
    root = repo(tmp_path)
    (root / "backend" / "syrax" / "quality.py").write_text("CHECK = 'research'\n")
    git(root, "add", "-A"); git(root, "commit", "-q", "-m", "judge")
    j = Journal(tmp_path / "j.db")
    human = j.start_task_sync("the human asks to change a case", kind="conversation")
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: human, snapshot_dir=tmp_path / "rb")
    dl.begin_task()
    (root / "backend" / "syrax" / "quality.py").write_text("CHECK = 'know'\n")
    with pytest.raises(ValueError, match="only a human changes it.*for them to review and commit"):
        asyncio.run(dl.release("change the case"))
    assert (root / "backend" / "syrax" / "quality.py").read_text() == "CHECK = 'know'\n"  # the human's edit stays


@pytest.mark.parametrize("path", [str(ROOT / "backend" / "syrax" / "quality.py"),
                                  str(ROOT / ".syrax" / "worktrees" / "abc123" / "backend" / "syrax" / "guard.py"),
                                  "backend/syrax/verify.py"])
def test_own_work_is_refused_writing_a_judge_at_the_call(path):
    d = permissions.classify("str_replace_editor", {"command": "str_replace", "path": path, "old_str": "a", "new_str": "b"})
    v = permissions.decide(d, "autonomous", "improve the editor")
    assert v.action == "refuse" and "only a human changes it" in v.reason
    assert permissions.decide(d, "eval", "x").action == "refuse"
    view = permissions.classify("str_replace_editor", {"command": "view", "path": path})
    assert permissions.decide(view, "autonomous", "read it").action == "allow"  # reading a judge is fine


def test_a_quality_case_never_releases():
    d = permissions.classify("release", {"summary": "x"})
    assert permissions.decide(d, "eval", "apply the patch").action == "refuse"
    assert permissions.decide(d, "autonomous", "improve").action == "allow"
    assert permissions.decide(d, "conversation", "release it").action == "allow"


def test_a_path_in_a_worktree_of_a_worktree_maps_to_the_repository():
    nested = "C:/ai-agent/son-of-ultron/.syrax/worktrees/1d1d0126f78f/.syrax/worktrees/abc123/backend/syrax/guard.py"
    assert permissions.repo_relative(nested) == "backend/syrax/guard.py"
    assert permissions.repo_relative("C:/x/.syrax/maintenance/m1/docs/RISE.md") == "docs/RISE.md"
    assert permissions.protected_targets([nested]) == ["backend/syrax/guard.py"]


def test_a_normal_own_edit_and_a_humans_request_are_allowed():
    own = permissions.classify("str_replace_editor", {"command": "create", "path": str(ROOT / "backend" / "syrax" / "newmod.py"), "file_text": "x"})
    assert permissions.decide(own, "autonomous", "add a module").action == "allow"
    judge = permissions.classify("str_replace_editor", {"command": "str_replace", "path": str(ROOT / "backend" / "syrax" / "quality.py"),
                                                       "old_str": "a", "new_str": "b"})
    assert permissions.decide(judge, "conversation", "change the case in quality.py").action == "allow"  # the human commits it
    code = permissions.classify("python_execute", {"code": "open(r'backend/syrax/guard.py', 'w').write('')"})
    assert permissions.decide(code, "autonomous", "x").action == "refuse"
