"""EVOLUTION_PLAN direction 87 (hyperparameter optimization): predicted_success used a hand-set Laplace prior,
(done + 1) / (finished + 2). Its strength is now chosen from SYRAX's own history: each finished objective is predicted
only from the objectives closed before it was created (prequential), the grid value with the lowest Brier score wins,
and it is adopted only from TUNE_MIN objectives and a TUNE_MARGIN gain over the default. Live 2026-10-30, 370
objectives: a = 4 scored 0.1499 against 0.1565 for a = 1."""

import asyncio
import json

from syrax import calibrate
from syrax.journal import Journal
from syrax.test_autonomy import make


def finished(j, kind, outcomes, t0=1000.0):
    for i, y in enumerate(outcomes):
        o = j.add_objective_sync(f"{kind} {i}", None, 3, "human", {"kind": kind, "path": f"/w/{kind}{i}"})
        j.update_objective_sync(o["id"], status="DONE" if y else "BLOCKED", note="past")
        j._db.execute("UPDATE objectives SET created=?, updated=? WHERE id=?", (t0 + 10 * i, t0 + 10 * i + 5, o["id"]))


def test_a_noisy_history_tunes_a_stronger_prior_and_it_is_used(tmp_path):
    j = Journal(tmp_path / "j.db")
    finished(j, "file_present", [1, 0] * 20)  # a coin: the default prior chases every outcome
    t = calibrate.tune_prior(j)
    scores = {a: calibrate.prequential_brier(j, a)[0] for a in calibrate.PRIOR_GRID}
    assert t["best"] == min(scores, key=scores.get) and t["best"] > 1 and t["adopted"]
    assert t["score"] <= t["baseline"] - calibrate.TUNE_MARGIN and t["n"] == 40
    j.set_meta("calibration_prior", json.dumps(t))
    a = t["best"]
    assert calibrate.prior_strength(j) == a
    assert calibrate.predicted_success(j, "file_present") == round((20 + a) / (40 + 2 * a), 3)


def test_too_little_history_keeps_the_default(tmp_path):
    j = Journal(tmp_path / "j.db")
    finished(j, "file_present", [1, 0] * 5)
    t = calibrate.tune_prior(j)
    assert not t["adopted"] and calibrate.prior_strength(j) == 1.0
    assert calibrate.predicted_success(j, "file_present") == round(6 / 12, 3)


def test_autonomy_tunes_once_a_day_and_records_a_change(tmp_path):
    j, core, a = make(tmp_path)
    finished(j, "file_present", [1, 0] * 20)
    asyncio.run(a._tune_prior())
    asyncio.run(a._tune_prior())  # the same day: nothing new
    ev = [e["payload"] for e in j.recent_events(100) if e["type"] == "hyperparameter.tuned"]
    assert len(ev) == 1 and ev[0]["name"] == "calibration_prior" and ev[0]["from"] == 1.0 and ev[0]["to"] > 1
    assert calibrate.prior_strength(j) == ev[0]["to"]
