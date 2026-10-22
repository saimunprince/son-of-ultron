"""Live 2026-10-19 (read of the self-change pipeline): covering_tests turned the system map's path entries, such as
"backend/syrax/test_bridge.py", into backend/syrax/test_bridge/py.py, so none of the 50 map test entries ever ran in
apply_patch or the release preflight. And a touched new test came after the module's importers, so with 16 or more
of those (agent.py has 22) the new test itself was cut from the run that should prove it."""

import json

from syrax.selfedit import MAX_TEST_FILES, covering_tests
from syrax.test_devloop import repo


def test_a_path_entry_of_the_system_map_is_run(tmp_path):
    root = repo(tmp_path)
    (root / "backend" / "syrax" / "test_flow.py").write_text("def test_x():\n    assert True\n")
    smap = {"components": [{"component": "Mod", "code": ["backend/syrax/mod.py"],
                            "tests": ["backend/syrax/test_flow.py (release section)"]}]}
    (root / "docs" / "system_map.json").write_text(json.dumps(smap))
    assert "backend/syrax/test_flow.py" in covering_tests(root, ["backend/syrax/mod.py"])


def test_a_touched_test_is_never_cut_by_the_cap(tmp_path):
    root = repo(tmp_path)
    for i in range(MAX_TEST_FILES + 4):
        (root / "backend" / "syrax" / f"test_user{i:02d}.py").write_text("from syrax.mod import VALUE\n\n\ndef test_v():\n    assert VALUE\n")
    new = "backend/syrax/test_zz_new.py"
    (root / new).write_text("from syrax.mod import VALUE\n\n\ndef test_v():\n    assert VALUE == 2\n")
    out = covering_tests(root, ["backend/syrax/mod.py", new])
    assert out[0] == new and len(out) == MAX_TEST_FILES


def test_module_entries_of_the_map_still_run(tmp_path):
    root = repo(tmp_path)
    (root / "backend" / "syrax" / "test_mod.py").write_text("def test_x():\n    assert True\n")
    smap = {"components": [{"component": "Mod", "code": ["backend/syrax/mod.py"], "tests": ["syrax.test_mod::*"]}]}
    (root / "docs" / "system_map.json").write_text(json.dumps(smap))
    assert covering_tests(root, ["backend/syrax/mod.py"]) == ["backend/syrax/test_mod.py"]
