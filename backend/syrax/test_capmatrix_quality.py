"""A later subset quality run must not hide a case that failed in the last
full run: each case keeps its latest verdict."""

import time

from syrax import capmatrix as cm
from syrax.journal import Journal


def test_each_quality_case_keeps_its_latest_verdict(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.add_quality_run_sync([{"id": "research_cite", "ok": False}, {"id": "act_delete", "ok": False}], 0.0, "BASELINE", brain="x")
    j.add_quality_run_sync([{"id": "act_delete", "ok": True}], 100.0, "PASS", brain="x")  # subset re-run
    j.close()
    q = cm.read_journal(tmp_path / "j.db", time.time())["quality"]
    assert q["id"] == 2
    assert q["cases"] == {"research_cite": False, "act_delete": True}
    assert q["runs"] == {"research_cite": 1, "act_delete": 2}
    row = cm.evaluate(cm.Capability("r", "R", cm.CURRENT, "here", quality_cases=["research_cite"]), {"quality": q, "tool_stats": {}}, {}, {}, time.time())
    assert row["status"] == cm.RED and "research_cite FAIL (#1)" in row["evidence"]
