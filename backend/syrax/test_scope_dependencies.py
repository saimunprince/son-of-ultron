"""Audit 2026-10-25, release-policy hole 3: backend/requirements-syrax.txt sat
inside SYRAX's self-modification scope although radar says changing
dependencies is the human's decision. A release touching it is refused with
that reason, in any task kind. And two more files judge SYRAX's own work:
selfedit.py chooses which tests the release preflight runs, syrax/conftest.py
is the environment the pytest gate runs in; both join the protected set."""

import asyncio

import pytest

from syrax import devloop, permissions
from syrax.devloop import JUDGES, SCOPE, DevLoop, judge_problems, scope_problems
from syrax.journal import Journal
from syrax.test_devloop import PASS, git, repo

ROOT = permissions.BACKEND_ROOT.parent
REQ = "backend/requirements-syrax.txt"
REASON = "dependencies are the owner's decision: propose, do not change"


def test_the_dependency_manifest_is_out_of_scope_with_its_own_reason():
    assert REQ not in SCOPE and REQ in devloop.DEPENDENCIES
    assert scope_problems({REQ: "M"}) == [f"{REQ}: {REASON}"]
    assert scope_problems({REQ: "??"}) == [f"{REQ}: {REASON}"]  # created new, the same answer
    assert scope_problems({"backend/syrax/mod.py": "M", "docs/x.md": "??"}) == []  # the rest of the scope is unchanged


@pytest.mark.parametrize("kind", ["autonomous", "conversation"])
def test_a_release_touching_requirements_is_refused_before_the_gate(tmp_path, kind):
    root = repo(tmp_path)
    (root / "backend" / "requirements-syrax.txt").write_text("ddgs\n")
    git(root, "add", "-A"); git(root, "commit", "-q", "-m", "deps")
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("add requests", kind=kind)
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    (root / "backend" / "requirements-syrax.txt").write_text("ddgs\nrequests\n")
    (root / "backend" / "syrax" / "mod.py").write_text("import requests\nVALUE = 1\n")
    with pytest.raises(ValueError, match=REASON):
        asyncio.run(dl.release("use requests", {"why": "objective", "risk": "none", "tests": "test_mod.py"}))
    assert j.count("verifications") == 0  # the gate never ran
    assert (root / "backend" / "requirements-syrax.txt").read_text() == "ddgs\nrequests\n"  # a refusal leaves the tree alone
    assert git(root, "log", "--format=%s") == "deps\ninit"


def test_the_preflight_chooser_and_the_test_environment_are_judges():
    assert "backend/syrax/selfedit.py" in JUDGES and "backend/syrax/conftest.py" in JUDGES
    for path in ("backend/syrax/selfedit.py", "backend/syrax/conftest.py"):
        assert any("judges SYRAX's own work" in p for p in judge_problems({path: "M"}))
        d = permissions.classify("str_replace_editor", {"command": "str_replace", "path": str(ROOT / path), "old_str": "a", "new_str": "b"})
        assert permissions.decide(d, "autonomous", "improve the preflight").action == "refuse"  # refused at the call too
