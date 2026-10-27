"""2026-10-27: a task whose answer kept a claim no tool backed now ends PARTIAL (core._run, reason claim_unproven).
autonomy wrote every PARTIAL attempt's lesson as "ran out of steps; ...", which is wrong for that case: the lesson now
names the unproven claim; a step limit is still "ran out of steps"."""

import inspect

from syrax import autonomy


def test_the_lesson_reads_the_reason_of_the_partial():
    src = inspect.getsource(autonomy)
    assert 'done.get("reason") == "claim_unproven"' in src
    assert "its answer claimed what no tool showed" in src and "ran out of steps; " in src
