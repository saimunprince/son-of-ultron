"""The gate's tests run on their own settings: a machine's local SYRAX_*
variables (a moved UI port, its allowed origins, isolation) never reach them
(live 2026-10-11: SYRAX_ALLOWED_ORIGINS for port 3001 turned 62 tests into
403 failures and blocked every release)."""

import sys

from syrax import verify as V


def test_inherited_syrax_settings_do_not_reach_a_hermetic_gate(monkeypatch):
    monkeypatch.setenv("SYRAX_ALLOWED_ORIGINS", "http://localhost:3001")
    monkeypatch.setenv("SYRAX_ISOLATE", "1")
    monkeypatch.setenv("UNRELATED_SETTING", "kept")
    probe = [sys.executable, "-c",
             "import os; print(os.environ.get('SYRAX_ALLOWED_ORIGINS'), os.environ.get('SYRAX_ISOLATE'), "
             "os.environ.get('SYRAX_BROWSER'), os.environ.get('UNRELATED_SETTING'))"]
    r = V.run_gate(V.Gate("probe", probe, env={"SYRAX_BROWSER": "0"}, drop_env_prefixes=("SYRAX_",)))
    assert r.status == "PASS" and "None None 0 kept" in r.evidence
    r = V.run_gate(V.Gate("probe", probe, env={"SYRAX_BROWSER": "0"}))  # without the rule everything is inherited
    assert "http://localhost:3001 1 0 kept" in r.evidence


def test_the_pytest_gate_is_hermetic():
    gate = [g for g in V.default_gates() if g.name == "pytest"][0]
    assert tuple(gate.drop_env_prefixes) == ("SYRAX_",) and gate.env["SYRAX_BROWSER"] == "0"
