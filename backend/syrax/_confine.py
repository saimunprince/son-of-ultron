"""OS-level confinement for a worker that runs model-written code (python_execute, skill calls).

guard.py is a guard rail inside Python: it wraps open() and friends, and code that uses os.open, a hard link, ctypes
or a subprocess with a clean environment walks past it (audit 2026-10-28). This module asks the kernel instead:

- ``own_group()``: the worker leads a process group of its own, so a timeout or a cancel kills everything it started
  with one ``killpg`` (before, the tree was found through psutil, which this machine did not have: nothing but the
  worker died on Linux).
- ``limits()``: CPU seconds, address space, file size and core dumps are capped with setrlimit.
- ``landlock(writable)``: Linux Landlock (kernel 5.13+, no package): from here on this process and everything it
  starts can create, change, rename or delete files only beneath the given paths, whatever path, symlink, hard link
  or subprocess it uses; reading is not restricted. With Landlock ABI 6+ it also may not signal processes outside
  its own domain (it cannot kill the server) nor reach abstract unix sockets outside it.

Standard library only (it runs first in a freshly spawned worker). It is a judge file (devloop.JUDGES): only a human
changes what confines SYRAX's own code.
"""

import ctypes
import os
import sys
from typing import Iterable, List, Optional

# x86_64, aarch64 and every other architecture with the generic syscall table use the same numbers
_SYS_CREATE_RULESET, _SYS_ADD_RULE, _SYS_RESTRICT_SELF = 444, 445, 446
_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38

# fs access rights (include/uapi/linux/landlock.h) and the ABI that brought each
WRITE_FILE, REMOVE_DIR, REMOVE_FILE = 1 << 1, 1 << 4, 1 << 5
MAKE_CHAR, MAKE_DIR, MAKE_REG, MAKE_SOCK, MAKE_FIFO, MAKE_BLOCK, MAKE_SYM = (1 << n for n in range(6, 13))
REFER = 1 << 13  # ABI 2: renames and links across directories
TRUNCATE = 1 << 14  # ABI 3
_FILE_RIGHTS = WRITE_FILE | TRUNCATE  # the rights a rule on a single file may carry
_SCOPE_ABSTRACT_UNIX_SOCKET, _SCOPE_SIGNAL = 1 << 0, 1 << 1  # ABI 6

MB = 1024 * 1024


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64),
                ("scoped", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def _libc():
    return ctypes.CDLL(None, use_errno=True)


def abi() -> int:
    """The kernel's Landlock ABI version, 0 where there is none (not Linux, too old, or turned off)."""
    if not sys.platform.startswith("linux"):
        return 0
    try:
        v = _libc().syscall(_SYS_CREATE_RULESET, None, ctypes.c_size_t(0), ctypes.c_uint32(_CREATE_RULESET_VERSION))
    except Exception:
        return 0
    return v if v > 0 else 0


def write_rights(version: int) -> int:
    rights = WRITE_FILE | REMOVE_DIR | REMOVE_FILE | MAKE_CHAR | MAKE_DIR | MAKE_REG | MAKE_SOCK | MAKE_FIFO | MAKE_BLOCK | MAKE_SYM
    if version >= 2:
        rights |= REFER
    if version >= 3:
        rights |= TRUNCATE
    return rights


def landlock(writable: Iterable[str]) -> List[str]:
    """Allow file changes only beneath ``writable`` for this process and all it starts. Returns the paths that were
    granted (a path that does not exist is skipped). Raises OSError when the kernel refuses: callers that require the
    boundary must not run the code then."""
    version = abi()
    if version < 1:
        raise OSError("Landlock is not available on this system")
    libc = _libc()
    handled = write_rights(version)
    attr = _RulesetAttr(handled, 0, (_SCOPE_SIGNAL | _SCOPE_ABSTRACT_UNIX_SOCKET) if version >= 6 else 0)
    size = 24 if version >= 6 else 16 if version >= 4 else 8  # older kernels know only the first fields
    ruleset = libc.syscall(_SYS_CREATE_RULESET, ctypes.byref(attr), ctypes.c_size_t(size), ctypes.c_uint32(0))
    if ruleset < 0:
        raise OSError(ctypes.get_errno(), f"landlock_create_ruleset: {os.strerror(ctypes.get_errno())}")
    granted = []
    try:
        for path in writable:
            try:
                fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            except OSError:
                continue
            try:
                is_dir = os.path.isdir(f"/proc/self/fd/{fd}")
                rule = _PathBeneathAttr(handled if is_dir else (handled & _FILE_RIGHTS), fd)
                if libc.syscall(_SYS_ADD_RULE, ctypes.c_int(ruleset), ctypes.c_int(_RULE_PATH_BENEATH),
                                ctypes.byref(rule), ctypes.c_uint32(0)) < 0:
                    raise OSError(ctypes.get_errno(), f"landlock_add_rule {path}: {os.strerror(ctypes.get_errno())}")
                granted.append(path)
            finally:
                os.close(fd)
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_NO_NEW_PRIVS)")
        if libc.syscall(_SYS_RESTRICT_SELF, ctypes.c_int(ruleset), ctypes.c_uint32(0)) < 0:
            raise OSError(ctypes.get_errno(), f"landlock_restrict_self: {os.strerror(ctypes.get_errno())}")
    finally:
        os.close(ruleset)
    return granted


def own_group() -> None:
    """Lead a new session and process group (POSIX), so the parent can kill the whole tree with killpg(pid)."""
    if hasattr(os, "setsid"):
        try:
            os.setsid()
        except OSError:
            pass  # already a group leader


def limits(cpu_s: Optional[int] = None, memory_mb: Optional[int] = None, file_mb: Optional[int] = None) -> dict:
    """setrlimit caps for this process and its children (POSIX; a no-op elsewhere). Only lowers limits."""
    try:
        import resource
    except ImportError:
        return {}
    applied = {}
    for name, value in (("RLIMIT_CPU", cpu_s), ("RLIMIT_AS", memory_mb and memory_mb * MB),
                        ("RLIMIT_FSIZE", file_mb and file_mb * MB), ("RLIMIT_CORE", 0)):
        if value is None or not hasattr(resource, name):
            continue
        which = getattr(resource, name)
        soft, hard = resource.getrlimit(which)
        new = value if hard == resource.RLIM_INFINITY else min(value, hard)
        try:
            resource.setrlimit(which, (new, new))
            applied[name] = new
        except (ValueError, OSError):
            pass
    return applied


def apply(spec: Optional[dict]) -> Optional[str]:
    """Apply a confinement spec in a worker, before it runs anything else. Returns None when the code may run, or the
    reason it must not (a required boundary could not be set: fail closed).

    spec keys: cpu_s, memory_mb, file_mb (limits), writable (paths), require_landlock (bool), tmpdir (TMPDIR)."""
    own_group()
    if not spec:
        return None
    limits(spec.get("cpu_s"), spec.get("memory_mb"), spec.get("file_mb"))
    if spec.get("tmpdir"):
        os.environ["TMPDIR"] = spec["tmpdir"]
        import tempfile

        tempfile.tempdir = None  # recomputed from TMPDIR on next use
    writable = spec.get("writable")
    if writable is None:
        return None
    try:
        landlock(writable)
    except OSError as e:
        if spec.get("require_landlock"):
            return f"the write boundary for this task could not be set ({e}); nothing ran"
    return None


def wrap(cmd: list, writable: Iterable[str]) -> list:
    """`cmd` run under a Landlock write boundary: the live server's copy of this file (never the tree under test, which
    could carry a changed one) applies it and then execs `cmd`. Unchanged where Landlock is absent."""
    if abi() < 1:
        return list(cmd)
    args = [sys.executable, os.path.abspath(__file__)]
    for path in writable:
        args += ["--write", str(path)]
    return [*args, "--", *map(str, cmd)]


def _main(argv: List[str]) -> int:
    """python _confine.py --write PATH [--write PATH ...] -- CMD ARGS...: confine, then exec CMD (fail closed)."""
    if "--" not in argv:
        sys.stderr.write("usage: _confine.py --write PATH ... -- CMD ...\n")
        return 2
    split = argv.index("--")
    opts, cmd = argv[:split], argv[split + 1:]
    writable = [opts[i + 1] for i, a in enumerate(opts) if a == "--write" and i + 1 < len(opts)]
    if not cmd:
        return 2
    try:
        landlock(writable + ["/dev/null", "/dev/shm"])
    except OSError as e:
        sys.stderr.write(f"confinement failed, nothing ran: {e}\n")
        return 126
    os.execvp(cmd[0], cmd)
    return 127  # not reached


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
