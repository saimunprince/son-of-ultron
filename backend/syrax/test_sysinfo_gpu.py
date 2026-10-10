from __future__ import annotations

import subprocess
from unittest.mock import patch
import pytest

from syrax import sysinfo


def test_gpu_success():
    canned = "NVIDIA GeForce RTX 3060, 12288, 1024, 7\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = canned
        res = sysinfo.gpu()
        assert res == {
            "name": "NVIDIA GeForce RTX 3060",
            "memory_total_mb": 12288,
            "memory_used_mb": 1024,
            "utilization_pct": 7,
        }


def test_gpu_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        res = sysinfo.gpu()
        assert res is None
