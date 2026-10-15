"""SYRAX's ledger of 2026-10-15 said "1 failed" and its JUnit report went with
the maintenance worktree, so nobody could say which test it was. The matrix
names the failing tests under the suite totals."""

from syrax import capmatrix as cm

JUNIT = """<testsuites><testsuite name="pytest" tests="3" failures="1" errors="1" skipped="0" time="2.0">
<testcase classname="syrax.test_memory" name="test_ok"/>
<testcase classname="syrax.test_memory" name="test_ws"><failure message="AssertionError: assert 1008 == 1000 | closed">trace</failure></testcase>
<testcase classname="syrax.test_hud" name="test_feed"><error message="">ImportError: no module named x</error></testcase>
</testsuite></testsuites>"""


def test_the_failing_tests_are_named_under_the_totals(tmp_path):
    p = tmp_path / "pytest.xml"
    p.write_text(JUNIT, encoding="utf-8")
    t = cm.junit_totals(p)
    assert (t["passed"], t["failed"], t["errors"]) == (1, 1, 1)
    assert t["failing"] == [{"test": "syrax.test_memory::test_ws", "message": "AssertionError: assert 1008 == 1000 | closed"},
                            {"test": "syrax.test_hud::test_feed", "message": "ImportError: no module named x"}]
    text = cm.render([], "abc1234", "j.db", t, None, generated="2026-10-15 12:00")
    assert "- failing: `syrax.test_memory::test_ws` (AssertionError: assert 1008 == 1000 / closed)" in text
    assert "- failing: `syrax.test_hud::test_feed` (ImportError: no module named x)" in text
