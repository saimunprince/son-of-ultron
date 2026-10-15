"""Live 2026-10-15 (objective 266, attempt 1): four releases were refused
because the covering tests failed, and the final then said "Brain latency
tracking implemented ..., with unit tests passing". A pass claimed after the
task's last test run failed is sent back once, then replaced."""

from app.tool.base import ToolResult
from syrax import selfedit
from syrax.agent import TEST_CLAIM, TEST_FALLBACK, state_of_tests
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_honest_claims import run_task


def test_what_counts_as_a_claimed_pass_and_a_test_run():
    for text in ("implemented, with unit tests passing", "All tests pass.", "the tests are now green", "Tests passed."):
        assert TEST_CLAIM.search(text), text
    for text in ("the tests that cover your change fail", "tests are not passing yet", "I could not get the tests to pass"):
        assert not TEST_CLAIM.search(text), text
    assert state_of_tests("apply_patch", "patched 2 file(s)\nTESTS FAIL: 1 failed, 46 passed") == "fail"
    assert state_of_tests("apply_patch", "patched 1 file(s)\nTESTS PASS: 3 passed") == "pass"
    assert state_of_tests("release", "Error: release refused: refused: the tests that cover your change fail, so ...") == "fail"
    assert state_of_tests("release", "RELEASE COMMITTED \u00b7 verification #29 GREEN") == "pass"
    assert state_of_tests("python_execute", "TESTS FAIL: 1 failed") is None  # only the tools that run the tests


def failing_patch(monkeypatch):
    async def fake(self, diff="", run_tests=True, **_):
        return ToolResult(output="patched 1 file(s)\nTESTS FAIL: 1 failed, 46 passed (syrax/test_brain_ms.py)")

    monkeypatch.setattr(selfedit.ApplyPatchTool, "execute", fake)


def test_a_pass_claimed_after_failing_tests_is_replaced(script, monkeypatch):
    failing_patch(monkeypatch)
    script.queue = [
        call("apply_patch", {"diff": "--- a/x\n+++ b/x\n"}),
        call("terminate", {"status": "success"}, "Brain latency is in place, with unit tests passing."),
        reply("Done: all tests pass."),  # the rewrite repeats the claim
    ]
    assert run_task("add brain latency")["result"] == TEST_FALLBACK and not script.queue


def test_an_honest_answer_after_failing_tests_stands(script, monkeypatch):
    failing_patch(monkeypatch)
    script.queue = [
        call("apply_patch", {"diff": "--- a/x\n+++ b/x\n"}),
        call("terminate", {"status": "success"}, "test_brain_ms.py still fails: the listener never sees an answered event."),
    ]
    assert run_task("add brain latency")["result"].startswith("test_brain_ms.py still fails")
