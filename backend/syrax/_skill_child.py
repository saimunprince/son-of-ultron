"""The skill worker: what runs in the child process IsolatedSkill starts for one call of a registered skill.

Audit 2026-10-25/27 (open item 8): a registered skill ran its execute() in a thread of the server process, outside the
guard python_execute's workers get, so a skill called with the journal's path (or brains.json, a backup) as its
argument could write it, and a call past its timeout ran on forever in the background. Each call now runs here, in a
process of its own: the guard is installed first (the same guard.child_env + guard.install as _pyexec_child, so every
Python the skill starts is guarded too), then the skill's module is imported, its Skill class instantiated and
execute(**kwargs) run on an event loop of its own. The result goes back over the pipe; the parent kills this process
and everything it started when the call runs past its timeout.

Like _pyexec_child it imports only the standard library at module level (the skill's own imports come after the
guard). It is a judge file (devloop.JUDGES): it installs the guard for every skill call, so only a human changes it.
"""

import sys
from typing import Any, List, Optional

# ToolResult and its subclasses in app.tool.base travel as their fields; the parent builds the same class again.
RESULT_FIELDS = ("output", "error", "base64_image", "system")


def load_class(module: str, file: Optional[str], qualname: str) -> Any:
    """The tool class: imported by its module name when that module is importable (a class in SYRAX's own code),
    else loaded from its file under the same module name (load_skill names a skill's module after its folder and
    mtime, which no import finds)."""
    import importlib
    import importlib.util

    try:
        spec = importlib.util.find_spec(module) if module and module != "__main__" else None
    except (ImportError, ValueError):
        spec = None
    if spec is not None:
        mod = importlib.import_module(module)
    else:
        if not file:
            raise ImportError(f"cannot find the module {module!r} of the skill")
        spec = importlib.util.spec_from_file_location(module, file)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {file}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module] = mod
        spec.loader.exec_module(mod)
    obj: Any = mod
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def _picklable(value: Any) -> Optional[bytes]:
    import pickle

    try:
        return pickle.dumps(value)
    except Exception:
        return None


def pack_result(value: Any) -> dict:
    """What execute() returned, in a form the parent can always read: a ToolResult as its class name and fields
    (each field as plain data, or its text when it is not), anything else pickled with its text beside it."""
    try:
        from app.tool.base import ToolResult
    except Exception:
        ToolResult = None
    if ToolResult is not None and isinstance(value, ToolResult):
        import json

        fields = {}
        for f in RESULT_FIELDS:
            v = getattr(value, f, None)
            try:  # plain data travels as it is; an object of the skill's own classes would not unpickle in the parent
                json.dumps(v)
                fields[f] = v
            except Exception:
                fields[f] = str(v)
        return {"kind": "tool_result", "cls": type(value).__name__, "fields": fields}
    try:
        text = str(value)
    except Exception:
        text = repr(value)
    return {"kind": "value", "pickled": _picklable(value), "text": text}


def pack_error(e: BaseException, stage: str) -> dict:
    import traceback

    return {"kind": "raised", "stage": stage, "type": type(e).__name__, "message": str(e),
            "pickled": _picklable(e) if isinstance(e, Exception) else None,
            "trace": "".join(traceback.format_exception(type(e), e, e.__traceback__))[-3000:]}


def run(module: str, file: Optional[str], qualname: str, kwargs: dict, conn, paths: List[str], extra_path: List[str],
        confine: Optional[dict] = None) -> None:
    """Runs in the child: guard this process and every Python it starts, import the skill, run one call, send the
    result back. The result is sent even when the skill raises, calls sys.exit, or the guard cannot be installed
    (then the skill never runs)."""
    result: dict = {"kind": "raised", "stage": "guard", "type": "RuntimeError", "message": "the skill worker did not run", "pickled": None}
    stage = "guard"
    try:
        from syrax import _confine

        # its own process group (killpg takes the tree), rlimits, and for SYRAX's own work the Landlock boundary
        # python_execute has (2026-10-29); a required boundary that cannot be set means the skill does not run
        refused = _confine.apply(confine)
        if refused:
            raise RuntimeError(refused)
        if not paths:
            raise RuntimeError("no protected paths were given; a skill does not run unguarded")
        from syrax import guard

        guard.child_env(paths)
        guard.install(paths)
        for p in extra_path:
            if p and p not in sys.path:
                sys.path.append(p)
        stage = "load"
        tool = load_class(module, file, qualname)()
        stage = "execute"
        import asyncio

        result = pack_result(asyncio.run(tool.execute(**kwargs)))
    except BaseException as e:  # SystemExit and KeyboardInterrupt too: they end this call, never the server
        result = pack_error(e, stage)
    finally:
        try:
            conn.send(result)
        except Exception:
            try:
                conn.send({"kind": "raised", "stage": "send", "type": "RuntimeError",
                           "message": "the skill's result could not be sent back", "pickled": None})
            except Exception:
                pass
        conn.close()
