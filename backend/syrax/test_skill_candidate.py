"""A revision of a VERIFIED skill is built and checked aside (audit 2026-10-27, mission Phase Four): it goes over the
live folder only when it passes the whole gate, so a failed revision leaves the known-good version live and VERIFIED
(live 10-15: pdf_text went VERIFIED -> FAILED until the human rolled back). And a skill's imports are checked: a
package that is not installed refuses the skill, installing one is the owner's decision."""

import asyncio
import json

from syrax import prebuilt
from syrax.skills import SkillCreateTool, content_hash, hash_sources, imported_modules, missing_dependencies
from syrax.test_skills import BAD_TEST, GOOD, GOOD_TEST, factory

SHOUT = GOOD.replace("str(len(text.split()))", "str(len(text.split())) + '!'")  # other behaviour
SHOUT_TEST = GOOD_TEST.replace('== "3"', '== "3!"').replace('== "0"', '== "0!"')
MISSING_PKG = "syrax_no_such_package_xyz"


def run(coro):
    return asyncio.run(coro)


def events(j, kind):
    return [e for e in j.recent_events() if e["type"] == kind]


def test_a_failed_revision_leaves_the_live_version_registered_and_verified(tmp_path):
    j, f, coll = factory(tmp_path)
    skill_dir = tmp_path / "skills" / "word_count"
    live = run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    assert live["status"] == "VERIFIED"
    row = run(f.create("word_count", "count words", SHOUT, BAD_TEST))
    # the revision failed and says so ...
    assert row["status"] == "FAILED" and row["revision_failed"] is True and row["evidence"]["stage"] == "test"
    assert (row["version"], row["code_version"]) == (2, 2) and row["content_hash"] == hash_sources(
        {"skill.py": SHOUT, "test_skill.py": BAD_TEST, "__init__.py": ""})
    assert row["live"] == {"status": "VERIFIED", "version": 1, "code_version": 1, "content_hash": live["content_hash"]}
    # ... and the live skill never moved: files, registry row, registration, the tool's answers
    assert (skill_dir / "skill.py").read_text() == GOOD and content_hash(skill_dir) == live["content_hash"]
    now = j.skill("word_count")
    assert (now["status"], now["version"], now["code_version"], now["content_hash"]) == ("VERIFIED", 1, 1, live["content_hash"])
    assert json.loads((skill_dir / "skill.json").read_text())["status"] == "VERIFIED"
    assert "word_count" in coll.tool_map and run(coll.execute(name="word_count", tool_input={"text": "a b"})).output == "2"
    assert f.kept_versions("word_count") == []  # nothing replaced, nothing kept
    # the candidate stays aside for inspection, outside the live folder
    cand = f.candidate_dir("word_count")
    assert cand == tmp_path / "skills" / ".candidates" / "skills" / "word_count" and (cand / "skill.py").read_text() == SHOUT
    assert json.loads((cand / "skill.json").read_text())["revision_failed"] is True
    ev = events(j, "skill.revision_failed")
    assert len(ev) == 1 and ev[0]["payload"]["skill"] == "word_count" and ev[0]["payload"]["stage"] == "test"
    assert "failed" in ev[0]["payload"]["evidence"] and ev[0]["payload"]["live_content_hash"] == live["content_hash"]
    assert not events(j, "skill.failed")
    assert f.list()[0]["status"] == "VERIFIED" and f.list()[0]["registered"] is True


def test_the_brain_is_told_the_revision_failed_and_the_old_version_is_live(tmp_path):
    j, f, coll = factory(tmp_path)
    create = SkillCreateTool()
    create.factory = f
    run(create.execute(name="word_count", purpose="count words", code=GOOD, test_code=GOOD_TEST))
    out = run(create.execute(name="word_count", purpose="count words", code=SHOUT, test_code=BAD_TEST))
    assert not out.error and "revision FAILED" in out.output and "assert" in out.output
    assert "previous version (v1, code v1" in out.output and "still live, registered and VERIFIED" in out.output
    assert "Not registered" not in out.output


def test_a_passing_revision_is_tested_aside_then_swapped_in(tmp_path):
    j, f, coll = factory(tmp_path)
    skill_dir = tmp_path / "skills" / "word_count"
    h1 = run(f.create("word_count", "count words", GOOD, GOOD_TEST))["content_hash"]
    # SHOUT_TEST fails against the live code: passing proves the candidate's own code was tested
    row = run(f.create("word_count", "count words", SHOUT, SHOUT_TEST))
    assert row["status"] == "VERIFIED" and (row["version"], row["code_version"]) == (2, 2) and not row.get("revision_failed")
    assert (skill_dir / "skill.py").read_text() == SHOUT and row["content_hash"] == content_hash(skill_dir) != h1
    assert run(coll.execute(name="word_count", tool_input={"text": "a b"})).output == "2!"
    assert f.kept_versions("word_count") == [1] and content_hash(skill_dir / ".versions" / "1") == h1
    assert not f.candidate_dir("word_count").exists()
    assert json.loads((skill_dir / "skill.json").read_text())["content_hash"] == row["content_hash"]
    # and the human's rollback still works over a swapped-in revision
    back = run(f.rollback("word_count"))
    assert back["status"] == "VERIFIED" and back["content_hash"] == h1 and run(coll.execute(name="word_count", tool_input={"text": "a b"})).output == "2"


def test_a_candidate_refused_by_safety_dependencies_or_load_never_touches_the_live_skill(tmp_path):
    j, f, coll = factory(tmp_path)
    skill_dir = tmp_path / "skills" / "word_count"
    live = run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    unsafe = GOOD.replace("from app.tool.base", "import shutil\nshutil.rmtree('C:/')\nfrom app.tool.base")
    missing = f"import {MISSING_PKG}\n" + GOOD
    unloadable = GOOD.replace('"required": ["text"]', '"required": []').replace("execute(self, text: str)", "execute(self, text: str, n: int = 1)")
    for code, stage in ((unsafe, "safety"), (missing, "dependencies"), (unloadable, "load")):
        row = run(f.create("word_count", "count words", code, GOOD_TEST))
        assert row["status"] == "FAILED" and row["revision_failed"] and row["evidence"]["stage"] == stage, (stage, row["evidence"])
        assert (skill_dir / "skill.py").read_text() == GOOD and j.skill("word_count")["status"] == "VERIFIED"
        assert j.skill("word_count")["content_hash"] == live["content_hash"] and "word_count" in coll.tool_map
    assert [e["payload"]["stage"] for e in events(j, "skill.revision_failed")] == ["safety", "dependencies", "load"]
    # after failures, a good revision still goes in
    assert run(f.create("word_count", "count words", SHOUT, SHOUT_TEST))["status"] == "VERIFIED"
    assert run(coll.execute(name="word_count", tool_input={"text": "a"})).output == "1!"


def test_a_first_time_or_failed_skill_is_written_in_place_as_before(tmp_path):
    j, f, coll = factory(tmp_path)
    skill_dir = tmp_path / "skills" / "word_count"
    row = run(f.create("word_count", "count words", GOOD, BAD_TEST))
    assert row["status"] == "FAILED" and not row.get("revision_failed") and (skill_dir / "test_skill.py").read_text() == BAD_TEST
    assert events(j, "skill.failed") and not f.candidate_dir("word_count").exists()
    row = run(f.create("word_count", "count words", GOOD, GOOD_TEST))  # a FAILED row has no live version to protect
    assert row["status"] == "VERIFIED" and not f.candidate_dir("word_count").exists() and "word_count" in coll.tool_map


def test_a_skill_importing_a_package_that_is_not_installed_is_refused_before_its_tests(tmp_path):
    j, f, coll = factory(tmp_path)
    code = f"import json\nimport {MISSING_PKG}.sub\n" + GOOD
    row = run(f.create("word_count", "count words", code, GOOD_TEST, dependencies=["urllib", MISSING_PKG]))
    assert row["status"] == "FAILED" and row["evidence"]["stage"] == "dependencies" and row["tests_passed"] == 0
    assert f"{MISSING_PKG} is not installed; installing a package is the owner's decision" in row["evidence"]["evidence"]
    assert "word_count" not in coll.tool_map
    assert not (tmp_path / "skills" / "word_count" / ".test-journal.db").exists()  # its tests never ran
    # the standard library, SYRAX's own packages and installed packages pass; declared stdlib names are ignored
    ok = "import os, json\nfrom urllib.parse import quote\nimport pydantic\nfrom syrax import journal\n" + GOOD
    test_ok = "import pytest\n" + GOOD_TEST
    assert run(f.create("word_count", "count words", ok, test_ok, dependencies=["urllib", "pytest"]))["status"] == "VERIFIED"


def test_imports_are_read_from_the_source_without_running_it(tmp_path):
    src = (
        "from __future__ import annotations\nimport os.path, numpy as np\nfrom . import sibling\nfrom .x import y\n"
        "try:\n    import optional_pkg\nexcept ImportError:\n    optional_pkg = None\n"
        "try:\n    import also_optional\nexcept (ModuleNotFoundError, OSError):\n    pass\n"
        "try:\n    import required_pkg\nexcept OSError:\n    pass\n"
        "def f():\n    import lazy_pkg\n"
    )
    assert imported_modules(src) == {"__future__", "os", "numpy", "required_pkg", "lazy_pkg"}
    assert imported_modules("import os\nos.system('x')\nclass Skill(") == set()  # not Python: the compile stage says so
    d = tmp_path / "s"
    d.mkdir()
    (d / "skill.py").write_text(f"import sys, pytest, app.tool.base, skills.other.skill, mine.x\nimport {MISSING_PKG}\n")
    assert missing_dependencies(d, own={"mine"}) == [MISSING_PKG]


def test_a_prebuilt_update_over_a_verified_install_still_swaps_and_keeps_the_old_one(tmp_path):
    j, f, coll = factory(tmp_path)
    shipped = tmp_path / "prebuilt" / "word_count"
    shipped.mkdir(parents=True)
    (shipped / "skill.py").write_text('"""Count words."""\n' + GOOD)
    (shipped / "test_skill.py").write_text(GOOD_TEST)
    assert run(prebuilt.install(f, root=tmp_path / "prebuilt")) == [{"skill": "word_count", "outcome": "VERIFIED", "installed": "new"}]
    (shipped / "skill.py").write_text('"""Count words."""\n' + SHOUT)
    (shipped / "test_skill.py").write_text(SHOUT_TEST)
    assert run(prebuilt.install(f, root=tmp_path / "prebuilt")) == [{"skill": "word_count", "outcome": "VERIFIED", "installed": "updated"}]
    assert run(coll.execute(name="word_count", tool_input={"text": "a"})).output == "1!" and f.kept_versions("word_count") == [1]
