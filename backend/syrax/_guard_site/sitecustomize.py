"""Loaded by every Python process started from SYRAX's python_execute (via
PYTHONPATH): install the journal/keys guard before any user code runs."""

import os
import sys

_paths = [p for p in os.environ.get("SYRAX_GUARD_PATHS", "").split(os.pathsep) if p]
if _paths:
    _backend = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _backend not in sys.path:
        sys.path.insert(0, _backend)
    try:
        from syrax.guard import install

        install(_paths)
    except Exception as _e:  # a guard that cannot load must not be silent
        sys.stderr.write(f"SYRAX guard not installed: {_e}\n")
