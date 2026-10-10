from __future__ import annotations

import subprocess
from unittest.mock import patch
import pytest

from syrax import sysinfo


def test_gpu_windows_cim_success():
    with patch("syrax.sysinfo.WINDOWS", True):
        with patch("subprocess.run") as mock_run:
            def side_effect(args, **kwargs):
                if "nvidia-smi" in args:
                    raise FileNotFoundError()
                res = subprocess.CompletedProcess(args, 0, '{"Name":"AMD Radeon(TM) Graphics","AdapterRAM":536870912}\n', '')
                return res
            mock_run.side_effect = side_effect
            res = sysinfo.gpu()
            assert res == {
                "name": "AMD Radeon(TM) Graphics",
                "memory_total_mb": 512,
                "memory_used_mb": None,
                "utilization_pct": None,
            }


def test_gpu_windows_cim_list():
    with patch("syrax.sysinfo.WINDOWS", True):
        with patch("subprocess.run") as mock_run:
            def side_effect(args, **kwargs):
                if "nvidia-smi" in args:
                    raise FileNotFoundError()
                res = subprocess.CompletedProcess(args, 0, '[{"Name":"Intel HD Graphics","AdapterRAM":1073741824}, {"Name":"AMD Radeon(TM) Graphics","AdapterRAM":536870912}]\n', '')
                return res
            mock_run.side_effect = side_effect
            res = sysinfo.gpu()
            assert res == {
                "name": "Intel HD Graphics",
                "memory_total_mb": 1024,
                "memory_used_mb": None,
                "utilization_pct": None,
            }


def test_gpu_windows_not_windows():
    with patch("syrax.sysinfo.WINDOWS", False):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            res = sysinfo.gpu()
            assert res is None
            # Verify powershell was never called
            for call in mock_run.call_args_list:
                assert "powershell" not in call[0][0]
