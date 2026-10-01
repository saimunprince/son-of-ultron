"""Phase 7: the brain scorecard and the order proposal come from evidence."""

import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax import scorecard  # noqa: E402
from syrax.journal import Journal  # noqa: E402


def graded_tasks(j, provider, ok, n):
    results = []
    for i in range(n):
        t = j.start_task_sync(f"{provider} case {i}", kind="eval")
        j.record_sync("brain.answered", {"provider": provider}, task_id=t)
        j.record_sync("final", {"text": "x"}, task_id=t)
        j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
        results.append({"id": f"c{i}", "ok": i < ok, "task_id": t})
    return results


def test_scorecard_credits_the_main_brain_and_smooths_quality(tmp_path):
    j = Journal(tmp_path / "j.db")
    res = graded_tasks(j, "gemini", 9, 10) + graded_tasks(j, "upstage", 5, 10)
    j.add_quality_run_sync(res, 70.0, "BASELINE")
    card = scorecard.compute(j)
    assert card["gemini"]["graded"] == 10 and card["gemini"]["quality"] == round(10 / 12, 2)
    assert card["upstage"]["quality"] == 0.5 and card["upstage"]["success_rate"] == 1.0
    assert "gemini: 10 tasks" in scorecard.render(card)


def test_order_proposal_only_for_a_clear_measured_gap(tmp_path):
    j = Journal(tmp_path / "j.db")
    res = graded_tasks(j, "gemini", 9, 10) + graded_tasks(j, "upstage", 5, 10)
    j.add_quality_run_sync(res, 70.0, "BASELINE")
    assert scorecard.order_proposal(scorecard.compute(j), ["gemini", "upstage"]) is None  # already in the right order
    prop = scorecard.daily_proposal(j, ["upstage", "gemini"])
    assert prop and "Moving gemini above upstage" in prop["proposal"]
    assert scorecard.daily_proposal(j, ["upstage", "gemini"]) is None  # the same finding is proposed once
