"""Keep code SYRAX runs (python_execute, and any Python it spawns) away from
the records that judge it and the keys it holds.

Live 2026-10-01: SYRAX read its journal with raw sqlite3 from python_execute
and, in a second process, wrote quality runs that closed its own objective.
The journal owner lock makes a second `Journal` read-only, but raw sqlite3 or
a plain file write would bypass it. Inside python_execute (and, through
`sitecustomize`, inside every Python process it starts):

- sqlite3.connect on a protected database opens it read-only;
- open/os.remove/os.replace/os.rename for writing a protected file raise
  PermissionError.

This is a guard rail against the paths SYRAX actually took, not a sandbox: a
shell command could still reach the files. The owner process itself never
installs it.
"""

from __future__ import annotations

import builtins
import os
from pathlib import Path
from typing import Iterable, List

ENV = "SYRAX_GUARD_PATHS"
SITE_DIR = str(Path(__file__).with_name("_guard_site"))
WRITE_FLAGS = ("w", "a", "+", "x")


def protected_paths() -> List[str]:
    """The files code run by SYRAX must not write: the journal and its
    sidecars, and the brain keys."""
    from syrax.journal import DEFAULT_FILE

    journal = Path(os.getenv("SYRAX_JOURNAL_FILE", str(DEFAULT_FILE))).resolve()
    keys = {str((journal.parent / "brains.json").resolve())}
    if os.getenv("SYRAX_BRAINS_FILE"):
        keys.add(str(Path(os.environ["SYRAX_BRAINS_FILE"]).resolve()))
    return [str(journal), f"{journal}-wal", f"{journal}-shm", f"{journal}.owner", *sorted(keys)]


def _norm(p) -> str:
    try:
        s = os.fspath(p)
    except TypeError:
        return ""
    if isinstance(s, bytes):
        s = s.decode(errors="replace")
    if s.startswith("file:"):
        s = s[5:].split("?", 1)[0]
    try:
        return os.path.normcase(str(Path(s).resolve()))
    except (OSError, ValueError):
        return os.path.normcase(s)


def install(paths: Iterable[str]) -> None:
    """Patch this interpreter. Idempotent."""
    guarded = {os.path.normcase(str(Path(p).resolve())) for p in paths if p}
    if not guarded or getattr(builtins, "_syrax_guard", False):
        return
    builtins._syrax_guard = True

    def is_protected(p) -> bool:
        return _norm(p) in guarded

    import sqlite3

    real_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        if is_protected(database):
            kwargs["uri"] = True
            database = f"file:{Path(_norm(database)).as_posix()}?mode=ro"
        return real_connect(database, *args, **kwargs)

    sqlite3.connect = connect

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if isinstance(mode, str) and any(f in mode for f in WRITE_FLAGS) and is_protected(file):
            raise PermissionError(f"{file}: SYRAX's journal and keys are written only by the running core")
        return real_open(file, mode, *args, **kwargs)

    builtins.open = guarded_open
    import io

    io.open = guarded_open

    for name in ("remove", "unlink", "replace", "rename"):
        real = getattr(os, name)

        def make(real=real, name=name):
            def wrapped(src, *args, **kwargs):
                targets = [src] + [a for a in args[:1]]
                if any(is_protected(t) for t in targets):
                    raise PermissionError(f"{src}: SYRAX's journal and keys cannot be {name}d from here")
                return real(src, *args, **kwargs)
            return wrapped

        setattr(os, name, make())


def child_env(paths: Iterable[str]) -> None:
    """Make Python processes started from here install the guard too."""
    os.environ[ENV] = os.pathsep.join(paths)
    pp = os.environ.get("PYTHONPATH", "")
    if SITE_DIR not in pp.split(os.pathsep):
        os.environ["PYTHONPATH"] = SITE_DIR + (os.pathsep + pp if pp else "")
