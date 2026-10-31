"""Live 2026-10-28..31: the daily ledger publish failed four times (144 tests failed in its gate) and the capability
matrix went four days stale. The server's install_git_safety puts git's safe config in the environment as
GIT_CONFIG_COUNT / GIT_CONFIG_KEY_n / GIT_CONFIG_VALUE_n; the confined gate's scrub_env removed GIT_CONFIG_KEY_n
("KEY" in the name) and kept the count, so every git inside the gate died with "missing config key GIT_CONFIG_KEY_0".
A git config key name is not a secret; its value was never scrubbed by name either."""

import os
import subprocess
import sys

from syrax import _confine, devloop


def test_git_config_key_names_are_not_secrets():
    env = devloop.git_safe_env({"PATH": os.environ["PATH"], "API_KEY": "x", "GITHUB_TOKEN": "y"})
    gone = _confine.scrub_env(env)
    assert "API_KEY" in gone and "GITHUB_TOKEN" in gone
    n = int(env["GIT_CONFIG_COUNT"])
    assert n >= 2 and all(f"GIT_CONFIG_KEY_{i}" in env and f"GIT_CONFIG_VALUE_{i}" in env for i in range(n))


def test_git_runs_under_the_confined_gate_with_the_safe_config(tmp_path):
    env = devloop.git_safe_env(dict(os.environ))
    env["TMPDIR"] = str(tmp_path)
    cmd = _confine.wrap(["git", "init", "-q", str(tmp_path / "r")], [tmp_path])
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_matrix_report_is_written_where_the_confined_gate_may_write(tmp_path, monkeypatch):
    from syrax import ledger, verify

    gate_tmp = tmp_path / "gate_tmp"
    gate_tmp.mkdir()
    seen = {}

    def fake_run(gate):
        arg = next(a for a in gate.cmd if a.startswith("--junitxml="))
        seen["path"] = arg.split("=", 1)[1]
        open(seen["path"], "w").write("<testsuites/>")

    real = verify.default_gates

    def gates(root):
        out = real(root)
        import dataclasses
        return [dataclasses.replace(g, env={**(g.env or {}), "TMPDIR": str(gate_tmp)}) if g.name == "pytest" else g for g in out]

    monkeypatch.setattr(verify, "default_gates", gates)
    monkeypatch.setattr(verify, "run_gate", fake_run)
    xml = tmp_path / "maintenance" / "wt-pytest.xml"
    assert ledger.run_junit(tmp_path, xml) and xml.read_text() == "<testsuites/>"
    assert seen["path"].startswith(str(gate_tmp))
