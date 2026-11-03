"""Audit 2026-11-01 (F15): a staged rename kept only its new path, so renaming an existing test away
(test_x.py -> helper.py) hid the deletion from the judges. The old path is listed as deleted."""

import subprocess

from syrax import devloop


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True, capture_output=True)


def test_a_renamed_test_shows_as_deleted(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "backend" / "syrax").mkdir(parents=True)
    (tmp_path / "backend" / "syrax" / "test_old.py").write_text("def test_a():\n    assert True\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    git(tmp_path, "mv", "backend/syrax/test_old.py", "backend/syrax/helper_old.py")
    files = devloop.changed_files(tmp_path)
    assert files["backend/syrax/test_old.py"] == "D" and files["backend/syrax/helper_old.py"] == "R"
