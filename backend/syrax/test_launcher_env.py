"""The service's defaults reach the core it spawns and nothing else: launching
leaves this process's environment as it was (the test suite imports the
launcher; a lasting setdefault once made test cycles run real ledger
publishes)."""

import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("syrax_launcher_env", ROOT / "syrax.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, value in (("LOG", tmp_path / "syrax.log"), ("PID_FILE", tmp_path / "syrax.pid"), ("_OUTPUT_IS_LOG", False),
                        ("setup", lambda verbose=False: None), ("check_config", lambda: None),
                        ("port_in_use", lambda port: False), ("ui_is_stale", lambda: False)):
        monkeypatch.setattr(mod, name, value)
    monkeypatch.setenv("SYRAX_OPEN_UI", "0")
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


def run(mod, monkeypatch):
    seen = {}

    class Fake:
        def __init__(self, name, cmd, cwd, log):
            self.name, self.proc = name, type("P", (), {"returncode": 0})()
            seen[name] = {k: os.environ.get(k) for k in mod.SERVICE_DEFAULTS}

        def alive(self):
            return self.name != "core"

        def stop(self):
            pass

    monkeypatch.setattr(mod, "Component", Fake)
    assert mod.launch(dev=False, service=True) == 0
    return seen


def test_the_core_gets_the_service_defaults_and_nothing_leaks(tmp_path, monkeypatch):
    names = ("SYRAX_ISOLATE", "SYRAX_PUBLISH_RISE", "SYRAX_CODEBENCH", "SYRAX_FEATURES")
    for k in names:
        monkeypatch.delenv(k, raising=False)
    mod = load(tmp_path, monkeypatch)
    seen = run(mod, monkeypatch)
    assert seen["core"] == {k: "1" for k in names}
    assert seen["ui"] == {k: None for k in names}  # only the core needs them
    assert not set(names) & set(os.environ)  # restored


def test_an_explicit_setting_wins_and_stays(tmp_path, monkeypatch):
    monkeypatch.setenv("SYRAX_PUBLISH_RISE", "0")
    monkeypatch.delenv("SYRAX_ISOLATE", raising=False)
    monkeypatch.delenv("SYRAX_CODEBENCH", raising=False)
    monkeypatch.delenv("SYRAX_FEATURES", raising=False)
    mod = load(tmp_path, monkeypatch)
    seen = run(mod, monkeypatch)
    assert seen["core"] == {"SYRAX_ISOLATE": "1", "SYRAX_PUBLISH_RISE": "0", "SYRAX_CODEBENCH": "1", "SYRAX_FEATURES": "1"}
    assert os.environ.get("SYRAX_PUBLISH_RISE") == "0" and "SYRAX_ISOLATE" not in os.environ
