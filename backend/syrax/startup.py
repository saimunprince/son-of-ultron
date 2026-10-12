"""Start with Windows: the human's switch for SYRAX starting at login.

Live 2026-10-12: Prince did not want SYRAX opening at every boot and asked for
an on/off in the UI. On Windows the login start is the user's Startup folder
entry that `syrax.py --install-service` writes when Task Scheduler needs admin;
this module reads, writes and removes exactly that entry. Turning it off never
stops the SYRAX that is running; it only decides the next login.

Other systems start SYRAX through their service managers (`syrax.py
--install-service`), which this switch reports as unsupported instead of guessing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from syrax.journal import BACKEND_ROOT

REPO_ROOT = BACKEND_ROOT.parent
NAME = "SYRAX.vbs"


def startup_dir() -> Path:
    override = os.getenv("SYRAX_STARTUP_DIR")  # tests point it at a temporary folder
    if override:
        return Path(override)
    return Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))) / "Microsoft/Windows/Start Menu/Programs/Startup"


def script() -> Path:
    return startup_dir() / NAME


def supported() -> bool:
    return sys.platform == "win32"


def command() -> list:
    """What syrax.py --install-service starts at login: the console-less venv
    interpreter running the launcher in service mode."""
    scripts = BACKEND_ROOT / ".venv" / "Scripts"  # the launcher's venv_pythonw(), same fallback
    py = scripts / "pythonw.exe" if (scripts / "pythonw.exe").exists() else scripts / "python.exe"
    return [str(py), str(REPO_ROOT / "syrax.py"), "--service"]


def vbs_text(cmd: Optional[list] = None) -> str:
    args = " ".join(f'""{a}""' for a in (cmd or command()))
    return f'CreateObject("WScript.Shell").Run "{args}", 0, False\r\n'


def status() -> Dict[str, Any]:
    if not supported():
        return {"supported": False, "enabled": False, "how": "use syrax.py --install-service on this system"}
    return {"supported": True, "enabled": script().is_file(), "how": f"Startup folder ({NAME})"}


def set_enabled(on: bool) -> Dict[str, Any]:
    if not supported():
        raise RuntimeError("start with the system is switched by syrax.py --install-service on this system")
    path = script()
    if on:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(vbs_text().encode("utf-8"))
    else:
        path.unlink(missing_ok=True)
    return status()
