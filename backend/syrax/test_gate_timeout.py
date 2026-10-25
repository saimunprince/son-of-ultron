"""2026-10-25: the gate's pytest step ran 559-843 s nine times that day as the suite grew past 1,100 tests, and
twice it was cut at the 900 s default while the machine was loaded (NOT_VERIFIED, a correct change held). The
pytest gate gets its own ceiling, 1500 s by default, settable with SYRAX_PYTEST_GATE_TIMEOUT_S; the other gates
keep theirs."""

from syrax import verify


def pytest_gate(gates):
    return next(g for g in gates if g.name == "pytest")


def test_the_pytest_gate_has_room_for_the_whole_suite(tmp_path, monkeypatch):
    monkeypatch.delenv("SYRAX_PYTEST_GATE_TIMEOUT_S", raising=False)
    gate = pytest_gate(verify.default_gates(tmp_path))
    assert gate.timeout == verify.PYTEST_GATE_TIMEOUT_S == 1500.0
    assert gate.timeout > verify.Gate("x", ["true"]).timeout  # the other gates keep the 900 s default


def test_the_owner_can_set_the_pytest_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("SYRAX_PYTEST_GATE_TIMEOUT_S", "2400")
    assert pytest_gate(verify.default_gates(tmp_path)).timeout == 2400.0
