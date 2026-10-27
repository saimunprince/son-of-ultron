"""The performance gate records every run into the journal it is given and
compares it with a PINNED baseline, not with whatever ran last.

Audit 2026-10-27: default_gates() called performance_gate(None) and the service
never set SYRAX_JOURNAL_FILE, so in 14 days 37 gate runs PASSed against nothing
and the benchmarks table never got a row."""

import pytest

from syrax import bench, verify
from syrax.devloop import DevLoop
from syrax.journal import Journal


def _perf(gates):
    return next(g for g in gates if g.name == "performance")


@pytest.fixture(autouse=True)
def _no_env_journal(monkeypatch):
    monkeypatch.delenv("SYRAX_JOURNAL_FILE", raising=False)


def test_two_gate_runs_record_two_rows_and_the_first_is_pinned(tmp_path):
    j = Journal(tmp_path / "j.db")
    gate = _perf(verify.default_gates(tmp_path, journal=j))
    assert gate.required is False  # advisory: evidence, not a blocker
    ok1, text1 = gate.cmd()
    assert ok1 and "BENCHMARK BASELINE" in text1 and "pinned as the baseline" in text1
    rows = j.benchmarks()
    assert len(rows) == 1 and j.get_meta(bench.BASELINE_KEY) == str(rows[0]["id"])
    first = rows[0]["id"]
    ok2, text2 = gate.cmd()
    rows = j.benchmarks()
    assert len(rows) == 2
    assert rows[0]["compared_to"] == first and f"vs pinned baseline #{first}" in text2
    assert j.get_meta(bench.BASELINE_KEY) == str(first)  # the pin does not move by itself
    assert "not recorded" not in text2
    j.close()


def test_a_later_run_compares_with_the_pinned_baseline_not_the_previous(tmp_path):
    j = Journal(tmp_path / "j.db")
    gate = _perf(verify.default_gates(tmp_path, journal=j))
    gate.cmd()
    base = j.benchmarks(limit=1)[0]
    slow = j.add_benchmark_sync({k: 1e6 for k in base["metrics"]}, "PASS", {})  # a slow run in between
    ok, text = gate.cmd()
    row = j.benchmarks(limit=1)[0]
    assert row["compared_to"] == base["id"] != slow["id"]
    d = next(iter(row["deltas"].values()))
    k = next(iter(row["deltas"]))
    assert d["before"] == base["metrics"][k] and d["prev"] == 1e6
    assert f"vs pinned baseline #{base['id']} and previous #{slow['id']}" in text
    j.close()


def test_creep_against_the_pinned_baseline_is_a_regression(tmp_path):
    j = Journal(tmp_path / "j.db")
    fast = j.add_benchmark_sync({k: 0.001 for k in bench.run_suite(tmp_path / "w")}, "BASELINE", {})
    bench.pin_baseline(j, fast["id"])
    j.add_benchmark_sync({k: 1e6 for k in fast["metrics"]}, "PASS", {})  # the previous run is slower than anything
    ok, text = verify.performance_gate(journal=j)
    assert not ok and "REGRESSION" in text and j.benchmarks(limit=1)[0]["compared_to"] == fast["id"]
    j.close()


def test_a_human_re_pins_from_the_cli(tmp_path, capsys):
    db = tmp_path / "j.db"
    j = Journal(db)
    a = j.add_benchmark_sync({"m": 1.0}, "BASELINE", {})
    b = j.add_benchmark_sync({"m": 2.0}, "PASS", {})
    j.close()
    assert bench.main(["--journal", str(db), "--pin-baseline", str(b["id"])]) == 0
    assert f"pinned benchmark #{b['id']}" in capsys.readouterr().out
    j = Journal(db, recover=False)
    assert j.get_meta(bench.BASELINE_KEY) == str(b["id"]) and bench.pinned_baseline(j)["id"] == b["id"] != a["id"]
    j.close()
    assert bench.main(["--journal", str(db), "--pin-baseline", "999"]) == 2


def test_without_a_journal_the_gate_says_not_recorded():
    ok, text = verify.performance_gate()
    assert ok and "BENCHMARK BASELINE" in text and "(no journal: not recorded)" in text
    ok, text = _perf(verify.default_gates()).cmd()
    assert "(no journal: not recorded)" in text


def test_devloop_gates_record_into_its_own_journal(tmp_path):
    j = Journal(tmp_path / "j.db")
    dl = DevLoop(j, root=tmp_path)
    ok, text = _perf(dl.gates()).cmd()
    assert "not recorded" not in text and len(j.benchmarks()) == 1
    j.close()


def test_the_cli_gate_records_into_the_journal_it_is_given(tmp_path, capsys):
    db = tmp_path / "j.db"
    assert verify.main(["--gate", "performance", "--journal", str(db)]) == 0
    capsys.readouterr()
    j = Journal(db, recover=False)
    assert len(j.benchmarks()) == 1 and j.get_meta(bench.BASELINE_KEY)
    assert len(j.verifications(limit=5)) == 1
    j.close()
