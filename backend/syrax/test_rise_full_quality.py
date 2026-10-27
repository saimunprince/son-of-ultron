"""2026-10-27 audit: the RISE quality metric took any run of 10+ cases as "the" pass rate, so the 12-case rotation
(run #86, 100 %) would have stood for the 67-case suite. A full run has at least 90 % of the largest run recorded up to
it; the suite may grow over time (52 cases, then 67) without its older full runs turning into subsets."""

import sqlite3
import time

from syrax import journal as jmod
from syrax import rise
from syrax.journal import Journal

DAY = 86400


def run(j, n, rate):
    j.add_quality_run_sync([{"id": f"c{i}", "ok": True} for i in range(n)], rate, "PASS", brain="x")


def metric(path, t0, t1):
    c = sqlite3.connect(path)
    try:
        return rise.quality_pass_rate(c, t0, t1)
    finally:
        c.close()


def test_a_rotation_subset_is_not_the_suite(tmp_path, monkeypatch):
    now = time.time()
    j = Journal(tmp_path / "j.db")
    monkeypatch.setattr(jmod, "_now", lambda: now - 2 * DAY)
    run(j, 67, 97.0)
    monkeypatch.setattr(jmod, "_now", lambda: now - DAY)
    run(j, 12, 100.0)  # the rotation: newer, 10+ cases, but a subset
    value, how = metric(tmp_path / "j.db", now - 7 * DAY, now)
    assert value == 97.0 and how.endswith("67 cases")


def test_a_grown_suite_keeps_its_older_full_runs(tmp_path, monkeypatch):
    now = time.time()
    j = Journal(tmp_path / "j.db")
    monkeypatch.setattr(jmod, "_now", lambda: now - 20 * DAY)
    run(j, 52, 90.4)
    monkeypatch.setattr(jmod, "_now", lambda: now - 10 * DAY)
    run(j, 12, 100.0)
    monkeypatch.setattr(jmod, "_now", lambda: now - 2 * DAY)
    run(j, 67, 95.5)
    assert metric(tmp_path / "j.db", now - 21 * DAY, now - 15 * DAY)[0] == 90.4  # full when it ran
    assert metric(tmp_path / "j.db", now - 12 * DAY, now - 8 * DAY) == (None, "no full quality run")
    assert metric(tmp_path / "j.db", now - 7 * DAY, now)[0] == 95.5


def test_a_small_suite_alone_is_still_below_the_floor(tmp_path, monkeypatch):
    now = time.time()
    j = Journal(tmp_path / "j.db")
    monkeypatch.setattr(jmod, "_now", lambda: now - DAY)
    run(j, 2, 100.0)
    assert metric(tmp_path / "j.db", now - 7 * DAY, now) == (None, "no full quality run")
