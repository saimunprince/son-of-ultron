"""EVOLUTION_PLAN wave 2 (directions 22, 30, 282): SYRAX never stated how likely an objective was to succeed, so it
could not learn whether its expectations were right. goal.selected now carries predicted_success (a Laplace rate over
finished objectives of the same check kind), and calibrate scores the predictions against outcomes."""

import asyncio

from syrax import autonomy as auto
from syrax import calibrate
from syrax.journal import Journal
from syrax.test_autonomy import make


def finished(j, kind, statuses):
    for i, st in enumerate(statuses):
        o = j.add_objective_sync(f"{kind} {i} {st}", source="human", check={"kind": kind, "tool": "desktop"} if kind == "tool_verified" else {"kind": kind, "topic": "x"})
        j.update_objective_sync(o["id"], status=st, note="test")


def test_the_prediction_is_the_smoothed_success_rate_of_the_same_kind(tmp_path):
    j = Journal(tmp_path / "j.db")
    assert calibrate.predicted_success(j, "tool_verified") == 0.5  # nothing known yet
    finished(j, "tool_verified", ["DONE", "DONE", "DONE", "BLOCKED"])
    finished(j, "knowledge_stored", ["BLOCKED", "BLOCKED"])
    assert calibrate.predicted_success(j, "tool_verified") == round(4 / 6, 3)
    assert calibrate.predicted_success(j, "knowledge_stored") == 0.25


def test_brier_and_bins():
    ps = [(0.9, 1), (0.9, 1), (0.9, 0), (0.1, 0)]
    assert calibrate.brier(ps) == round((0.01 + 0.01 + 0.81 + 0.01) / 4, 4)
    b = {x["from"]: x for x in calibrate.bins(ps)}
    assert b[0.8]["n"] == 3 and b[0.8]["observed"] == round(2 / 3, 3) and b[0.0]["observed"] == 0


def test_a_selection_states_its_prediction_and_is_scored_once_the_objective_ends(tmp_path, monkeypatch):
    j, core, a = make(tmp_path)
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    finished(j, "tool_verified", ["DONE", "DONE"])
    o = j.add_objective_sync("Verify the desktop tool", None, 1, "human", {"kind": "tool_verified", "tool": "desktop"})
    asyncio.run(a._selected(j.objective(o["id"])))
    sel = j.events_of_type("goal.selected", limit=1)[0]["payload"]
    assert sel["objective_id"] == o["id"] and sel["predicted_success"] == 0.75
    assert calibrate.summary(j)["n"] == 0  # still open: nothing to score
    j.update_objective_sync(o["id"], status="BLOCKED", note="test")
    s = calibrate.summary(j)
    assert s["n"] == 1 and s["brier"] == round(0.75 ** 2, 4) and s["verdict"] == "poorly calibrated"
    assert core.selfmodel.performance()["calibration"]["n"] == 1
