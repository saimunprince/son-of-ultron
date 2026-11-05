"""Live 2026-11-01: the login service (systemd --user) failed at start with "No such file or directory: 'npx'": the
user manager does not read the shell's PATH, and node lives in ~/.local/bin. The unit now carries the installing
shell's PATH, with the system folders kept."""

import importlib.util
import sys
from pathlib import Path

import pytest


def launcher():
    spec = importlib.util.spec_from_file_location("syrax_launcher", Path(__file__).resolve().parents[2] / "syrax.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(sys.platform == "win32", reason="the systemd service path is POSIX")
def test_the_service_path_keeps_the_shell_path_and_the_system_folders(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("node", "npx"):
        f = bin_dir / tool
        f.write_text("#!/bin/sh\n")
        f.chmod(0o755)
    path = launcher().service_path({"PATH": f"{bin_dir}:/usr/bin"})
    parts = path.split(":")
    assert parts[0] == str(bin_dir) and "/usr/bin" in parts and "/bin" in parts and len(parts) == len(set(parts))
