"""Live 2026-10-15 (objective 252, attempt 1): the brains answered empty, and
"The new test file has been created and the change is ready for release"
stood as the task's result after two rejections, although nothing was edited.
A claim that survives its rewrite, or a rewrite no brain answered, becomes a
plain statement that nothing was changed."""

from syrax.agent import CLAIM_FALLBACK
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_honest_claims import run_task


def test_a_claim_that_survives_its_rewrite_is_replaced(script):
    script.queue = [
        call("str_replace_editor", {"command": "view", "path": __file__}),
        call("terminate", {"status": "success"}, "The new test file has been created and the change is ready for release."),
        reply("Done: the test file has been created."),  # answer to the world-claim nudge: still nothing done
        reply("I have implemented the change."),  # answer to the honest rewrite: still a claim
    ]
    task = run_task("add a test for task durations")
    assert task["result"] == CLAIM_FALLBACK and not script.queue


def test_an_honest_rewrite_stands(script):
    script.queue = [
        call("python_execute", {"code": "print('3 failing cases')"}),
        call("terminate", {"status": "success"}, "Fixed the quality regression."),
        reply("Found 3 failing cases; nothing is changed yet."),
    ]
    assert run_task("fix the quality regression")["result"] == "Found 3 failing cases; nothing is changed yet."
