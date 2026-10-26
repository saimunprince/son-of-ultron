"""The python_execute worker: what runs in the child process AsyncPythonExecute starts.

The worker is started with the "spawn" method (the only one on Windows), so the child imports the module that holds
its target before it can run anything. When the target was AsyncPythonExecute._guarded_run, every worker imported
syrax.tools and with it app.tool, pydantic, docker and structlog: 0.7-1.0 s per call against 0.04 s for a bare
interpreter (profiled 2026-10-26). This module imports only the standard library, and syrax.guard inside the
worker, so a worker starts in a fraction of that and nothing heavy is loaded before the guard is installed.

It is a judge file (devloop.JUDGES): it installs the guard in every worker, so only a human changes it.
"""

import sys
from io import StringIO
from typing import Optional

# Live 2026-10-11 (objective 117): six python_execute failures in a week were
# "name 'os' is not defined": a brain imported os in one call and used it in the
# next, as if the calls shared a session. Each call is a fresh process; these are
# imported in it already, and the tool says so.
PRELOADED = ("os", "sys", "json", "re", "math", "time", "datetime", "shutil", "subprocess", "glob", "pathlib")


def _utf8_by_default(builtins_dict: dict) -> None:
    """In the python_execute child, text files are UTF-8 unless the code names an encoding. On Windows the
    default is the ANSI code page (cp1252): live 2026-10-15 a report written with open() held "78.37 °C" as
    one cp1252 byte and broke the quality checker, and reads of the repository's UTF-8 files failed with
    "'charmap' codec can't decode byte". open() and pathlib's read_text/write_text/open both follow this."""
    import io

    guarded_open = builtins_dict["open"]

    def open_utf8(file, mode="r", buffering=-1, encoding=None, *args, **kwargs):
        if encoding is None and "b" not in mode:
            encoding = "utf-8"
        return guarded_open(file, mode, buffering, encoding, *args, **kwargs)

    builtins_dict["open"] = open_utf8
    io.text_encoding = lambda encoding, stacklevel=2: "utf-8" if encoding is None else encoding


class _PrintedOutput(StringIO):
    """The code's stdout: kept for the result and written through, line by line, to a file the parent can read when
    it has to stop a code that runs past its timeout. Live 2026-10-19 (quality run #51, self_map_protected): two calls
    that walked the whole repository, .venv included, were stopped at 60 s with nothing but "Execution timeout after
    60 seconds"; what they had printed was lost."""

    def __init__(self, path: Optional[str] = None):
        super().__init__()
        try:
            self._file = open(path, "a", encoding="utf-8", errors="replace", buffering=1) if path else None
        except OSError:
            self._file = None

    def write(self, s: str) -> int:
        if self._file is not None:
            try:
                self._file.write(s)
            except Exception:
                self._file = None
        return super().write(s)

    def close_file(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None


def guarded_run(code: str, conn, safe_globals: dict, paths: list, out_path: Optional[str] = None) -> None:
    """Runs in the child: guard the journal and keys, for this process and
    every Python it starts, run the code, and send the result back. The
    result is sent even when the code calls sys.exit or the guard fails."""
    result = {"observation": "", "success": False}
    try:
        from syrax import guard

        guard.child_env(paths)
        guard.install(paths)
        import builtins

        safe_globals["__builtins__"] = builtins.__dict__.copy()  # the copy made before the guard holds the unguarded open
        _utf8_by_default(safe_globals["__builtins__"])
        import importlib

        for name in PRELOADED:  # the same (guarded) modules the code would get by importing them
            safe_globals.setdefault(name, importlib.import_module(name))
        safe_globals.setdefault("Path", safe_globals["pathlib"].Path)
        run_code(code, result, safe_globals, out_path)
    except Exception as e:  # the guard itself failed; the code never ran
        result["observation"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            conn.send(result)
        except Exception:
            pass
        conn.close()


def run_code(code: str, result_dict: dict, safe_globals: dict, out_path: Optional[str] = None) -> None:
    """Upstream's, with the exception's type in the observation ("name 'os' is not defined" alone does not say
    it was a NameError) after what the code printed before it raised, and the output kept when the code calls
    sys.exit (it still did not finish)."""
    original_stdout = sys.stdout
    output_buffer = _PrintedOutput(out_path)
    try:
        sys.stdout = output_buffer
        exec(code, safe_globals, safe_globals)
        result_dict["observation"] = output_buffer.getvalue()
        result_dict["success"] = True
    except Exception as e:
        printed = output_buffer.getvalue()
        if printed and not printed.endswith("\n"):
            printed += "\n"
        result_dict["observation"] = printed + f"{type(e).__name__}: {e}"
        result_dict["success"] = False
    except SystemExit as e:
        # Live 2026-10-14 (objective 232): three runs of `pytest.main([...])` ended with `sys.exit(code)` and answered
        # an empty observation; the whole pytest report was lost. It is kept now; the call still did not finish.
        result_dict["observation"] = output_buffer.getvalue() + f"\n(the code called sys.exit({e.code!r}); it did not finish)"
        result_dict["success"] = False
    finally:
        sys.stdout = original_stdout
        output_buffer.close_file()
