"""Quality run #48 (2026-10-19): apply_patch created a module no test covers and answered "TESTS PASS: no
covering tests found", so the agent counted a test run that never happened as a pass. And its description ended
"Then call `release`.", so the brain called release in three cases whose prompt said "Do not call release"."""

from syrax import selfedit
from syrax.agent import state_of_tests

NO_TEST = {"ok": True, "ran": [], "summary": "no covering tests found: write one (backend/syrax/test_<module>.py) before you release", "tail": ""}


def report(tests):
    return {"files": ["backend/syrax/_probe_case.py"], "root": "C:/repo", "compiled": ["backend/syrax/_probe_case.py"], "tests": tests}


def test_no_covering_test_is_not_reported_as_a_pass():
    out = selfedit.render_report(report(NO_TEST))
    assert "TESTS NOT RUN: no covering tests found" in out and "TESTS PASS" not in out
    assert state_of_tests("apply_patch", out) is None


def test_tests_that_ran_still_say_pass_or_fail():
    ok = selfedit.render_report(report({"ok": True, "ran": ["syrax/test_mod.py"], "summary": "1 passed", "tail": ""}))
    assert "TESTS PASS: 1 passed (syrax/test_mod.py)" in ok and state_of_tests("apply_patch", ok) == "pass"
    bad = selfedit.render_report(report({"ok": False, "ran": [], "summary": "not run: python does not compile: x", "tail": ""}))
    assert "TESTS FAIL: not run" in bad and state_of_tests("apply_patch", bad) == "fail"


def test_the_tool_does_not_tell_the_brain_to_release_against_the_human():
    d = selfedit.ApplyPatchTool().description
    assert "Then call `release`." not in d and "unless you were told not to" in d
