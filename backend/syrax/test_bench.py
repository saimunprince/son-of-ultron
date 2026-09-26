"""Benchmarks: measured on a scratch journal, compared with the last run, never asserted."""

from syrax import bench
from syrax.journal import Journal
from syrax.verify import performance_gate


def test_suite_measures_every_metric(tmp_path):
    m = bench.run_suite(tmp_path)
    assert set(m) == {"journal_record_p50_ms", "journal_record_p95_ms", "checkpoint_p95_ms", "tool_stats_ms", "events_between_ms", "recovery_ms", "selfmodel_summary_ms"}
    assert all(v >= 0 for v in m.values()) and m["journal_record_p95_ms"] >= m["journal_record_p50_ms"]


def test_compare_flags_only_real_regressions():
    prev = {"a": 10.0, "b": 100.0, "c": 1.0}
    status, d = bench.compare({"a": 10.5, "b": 200.0, "c": 3.0, "new": 4.0}, prev)
    assert status == "REGRESSION"
    assert d["a"]["regression"] is False and d["b"]["regression"] is True and d["b"]["pct"] == 100.0
    assert d["c"]["regression"] is False  # +200% but only +2 ms: jitter, not a regression
    assert d["new"]["before"] is None and d["new"]["regression"] is False
    assert bench.compare({"a": 12.0}, prev)[0] == "PASS"
    assert bench.compare({"a": 1.0}, None)[0] == "BASELINE"


def test_run_and_record_baseline_then_pass_or_regression(tmp_path):
    j = Journal(tmp_path / "j.db")
    first = bench.run_and_record(j)
    assert first["status"] == "BASELINE" and first["compared_to"] is None and first["git_head"]
    second = bench.run_and_record(j)
    assert second["status"] in ("PASS", "REGRESSION") and second["compared_to"] == first["id"]
    # plant a fake fast previous run: the next run must be flagged as a regression
    j.add_benchmark_sync({k: 0.001 for k in first["metrics"]}, "PASS", {})
    third = bench.run_and_record(j)
    assert third["status"] == "REGRESSION" and any(d["regression"] for d in third["deltas"].values())
    kinds = [e["type"] for e in j.recent_events()]
    assert kinds.count("benchmark.completed") == 4
    assert "REGRESSION" in bench.format_report(third) and "BENCHMARK BASELINE" in bench.format_report(first)


def test_performance_gate_uses_the_journal(tmp_path):
    ok, text = performance_gate(str(tmp_path / "g.db"))
    assert ok and "BENCHMARK BASELINE" in text
    j = Journal(tmp_path / "g.db", recover=False)
    j.add_benchmark_sync({k: 0.001 for k in bench.run_suite(tmp_path / "w")}, "PASS", {})
    j.close()
    ok, text = performance_gate(str(tmp_path / "g.db"))
    assert not ok and "REGRESSION" in text


def test_cli_without_journal_reports_baseline(capsys):
    assert bench.main([]) == 0
    assert capsys.readouterr().out.startswith("BENCHMARK BASELINE")


def test_suite_cleans_its_scratch_directory():
    import glob

    before = set(glob.glob("/tmp/syrax-bench-*"))
    bench.run_suite()
    assert set(glob.glob("/tmp/syrax-bench-*")) - before == set()
