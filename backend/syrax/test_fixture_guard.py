"""Live 2026-10-14 (task ee5bb152e8fa): working on "make quality case
self_patch_stale pass", SYRAX rewrote README's title so the case's stale patch
would apply, and the gate passed it. An objective born from a quality case may
change SYRAX's behaviour, never the files that case works on."""

import asyncio

import pytest

from syrax.devloop import DevLoop, case_files, fixture_problems
from syrax.journal import Journal
from syrax.test_devloop import PASS, git, repo

PLAN = {"why": "objective", "risk": "none", "tests": "test_fixture_guard.py"}


def test_the_files_a_case_names_are_found_in_its_prompt():
    named = case_files(["self_patch_stale", "self_patch_docs", "self_patch_edit"])
    assert named["README.md"] == ["self_patch_stale"]
    assert named["docs/EXECUTION_PLAN.md"] == ["self_patch_docs"]
    assert named["backend/syrax/selfedit.py"] == ["self_patch_edit"]
    assert case_files(["arith"]) == {}


def test_only_objectives_born_from_cases_are_held_to_it():
    files = {"README.md": "M", "backend/syrax/agent.py": "M"}
    case = {"check_spec": {"kind": "quality_case_passes", "case": "self_patch_stale"}}
    assert [p.split(":")[0] for p in fixture_problems(files, case)] == ["README.md"]
    regressed = {"check_spec": {"kind": "quality_recovered"}, "evidence": {"quality": {"failed": ["self_patch_docs"]}}}
    assert fixture_problems({"docs/EXECUTION_PLAN.md": "M"}, regressed)
    assert fixture_problems(files, {"check_spec": {"kind": "change_released"}}) == []
    assert fixture_problems(files, None) == []


def test_an_autonomous_release_for_a_case_may_not_rewrite_what_the_case_works_on(tmp_path):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("Quality case self_patch_stale failed", None, 3, "quality",
                             {"kind": "quality_case_passes", "case": "self_patch_stale"})
    j.update_objective_sync(o["id"], status="ACTIVE")
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] make the case pass", kind="autonomous")
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    dl.begin_task()
    (root / "README.md").write_text("# SYRAX probe\n")
    with pytest.raises(ValueError, match="named by quality case self_patch_stale"):
        asyncio.run(dl.release("make the stale patch apply", PLAN))
    assert (root / "README.md").read_text() == "# SYRAX probe\n"  # refused before the gate; the task's cleanup restores it
    (root / "README.md").write_text("# repo\n")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 2\n")
    assert asyncio.run(dl.release("change SYRAX itself", PLAN))["outcome"] == "COMMITTED"
