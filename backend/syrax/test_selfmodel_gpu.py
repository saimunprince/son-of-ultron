import pytest
from pathlib import Path
from syrax.journal import Journal
from syrax.selfmodel import SelfModel
from syrax import selfmodel
from syrax import sysinfo


def test_selfmodel_gpu(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    model = SelfModel(j)

    # Mock sysinfo.gpu to return a test dict
    monkeypatch.setattr(sysinfo, "gpu", lambda: {'name': 'Test GPU', 'memory_total_mb': 512})
    selfmodel._gpu.cache_clear()

    runtime_info = model.runtime()
    assert runtime_info["gpu"] == {'name': 'Test GPU', 'memory_total_mb': 512}

    # Mock sysinfo.gpu to return None
    monkeypatch.setattr(sysinfo, "gpu", lambda: None)
    selfmodel._gpu.cache_clear()

    runtime_info_none = model.runtime()
    assert runtime_info_none["gpu"] is None
