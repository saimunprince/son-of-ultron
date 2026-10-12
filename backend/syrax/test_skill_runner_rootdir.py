"""A skill's tests see only the skill's own folder: pytest is pinned to it with
--rootdir, so a folder that cannot be read next to the skill root (a dangling
junction here, a Chrome temp folder vanishing mid-listing in the gate of
2026-10-12) never fails a good skill."""

import os
import subprocess
import sys

import pytest

from syrax.skills import run_skill_tests
from syrax.test_skills import GOOD, GOOD_TEST


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows thing")
def test_an_unreadable_neighbour_folder_does_not_fail_a_good_skill(tmp_path):
    d = tmp_path / "skills" / "word_count"
    d.mkdir(parents=True)
    (d / "skill.py").write_text(GOOD)
    (d / "test_skill.py").write_text(GOOD_TEST)
    (d / "__init__.py").write_text("")
    gone = tmp_path / "gone"
    gone.mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(tmp_path / "dangling"), str(gone)], check=True, capture_output=True)
    os.rmdir(gone)  # the junction now points nowhere, like a temp folder deleted while it was being listed
    try:
        out = run_skill_tests(d)
        assert out["status"] == "VERIFIED" and out["passed"] == 2, out["evidence"]
    finally:
        os.rmdir(tmp_path / "dangling")  # removes the link only
