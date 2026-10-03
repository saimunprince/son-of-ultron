"""SYRAX's file editor: OpenManus' str_replace_editor with the mistakes models
actually make turned into either a safe fix or a precise error.

Measured on 2026-09-30 (22 ok / 11 failed): a missing `path` crashed with a
Python TypeError, relative paths were refused, `create` on an existing file was
refused, a `view_range` past the end was refused, and an `old_str` with the
wrong indentation found nothing. The tool keeps its name and parameters, so
journal evidence, devloop ownership and prompts are unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

from app.exceptions import ToolError
from app.tool.str_replace_editor import StrReplaceEditor

from syrax.journal import BACKEND_ROOT

REPO_ROOT = BACKEND_ROOT.parent
WORKSPACE = BACKEND_ROOT / "workspace"


def resolve_path(raw: str, command: str) -> Tuple[Path, Optional[str]]:
    """An absolute path for ``raw`` and a note when it had to be resolved.
    Relative paths are tried against the repository, the backend and the
    workspace; an existing file wins, a `create` goes where its folder exists
    (the workspace when none does)."""
    p = Path(str(raw).strip().strip('"').strip("'"))
    if p.is_absolute():
        return p, None
    bases = [REPO_ROOT, BACKEND_ROOT, WORKSPACE]
    for base in bases:
        cand = base / p
        if cand.exists():
            return cand, f"(relative path {raw} resolved to {cand})"
    if command == "create":
        for base in bases:
            cand = base / p
            if (cand.parent.is_dir() and cand.parent != base) or base is WORKSPACE:
                return cand, f"(relative path {raw} resolved to {cand})"
    raise ToolError(
        f"The path {raw} is not absolute and was not found under {REPO_ROOT}, {BACKEND_ROOT} or {WORKSPACE}. "
        "Use an absolute path."
    )


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def find_loose(content: str, old: str) -> List[int]:
    """Start line indexes where ``old`` matches ``content`` line by line when
    leading/trailing whitespace is ignored."""
    want = [ln.strip() for ln in old.strip("\n").split("\n")]
    if not any(want):
        return []
    lines = content.split("\n")
    hits = []
    for i in range(len(lines) - len(want) + 1):
        if all(lines[i + k].strip() == want[k] for k in range(len(want))):
            hits.append(i)
    return hits


def reindent(new: str, old: str, actual_first: str) -> str:
    """Shift ``new`` by the indentation difference between what the model wrote
    (``old``) and what the file has (``actual_first``)."""
    old_first = old.strip("\n").split("\n")[0]
    have, said = _indent(actual_first), _indent(old_first)
    out = []
    for ln in new.split("\n"):
        if ln.strip() and ln.startswith(said):
            ln = have + ln[len(said):]
        elif ln.strip() and not said:
            ln = have + ln
        out.append(ln)
    return "\n".join(out)


SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", ".cache"}


def list_directory(path: Path, depth: int = 2, limit: int = 400) -> str:
    """What `view` shows for a directory, in Python: OpenManus shells out to
    Unix `find`, which on Windows is a different program ("FIND: Parameter
    format not correct", seen live)."""
    rows: List[str] = []
    base_depth = len(path.parts)
    for root, dirs, files in __import__("os").walk(path):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        here = Path(root)
        level = len(here.parts) - base_depth
        if level >= depth:
            dirs[:] = []
        for name in dirs + sorted(f for f in files if not f.startswith(".")):
            rows.append(str(here / name) + ("/" if name in dirs else ""))
            if len(rows) >= limit:
                return "\n".join(rows) + f"\n… (stopped at {limit} entries)"
    return "\n".join(rows)


class SyraxEditor(StrReplaceEditor):
    # OpenManus' description and schema cost 632 tokens on every model call;
    # this says the same in about a third (measured with brains.count_tokens).
    description: str = (
        "View, create and edit files. view: a file (cat -n) or a directory (2 levels). create: write file_text "
        "(overwrites; undo_edit restores). str_replace: replace old_str, which must match once (indentation-tolerant), "
        "with new_str. insert: new_str after line insert_line. undo_edit: revert the last edit. Use absolute paths. "
        "It cannot delete files: use python_execute (os.remove)."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "enum": ["view", "create", "str_replace", "insert", "undo_edit"]},
            "path": {"type": "string", "description": "absolute path"},
            "file_text": {"type": "string", "description": "create: full content"},
            "old_str": {"type": "string", "description": "str_replace: text to replace"},
            "new_str": {"type": "string", "description": "str_replace/insert: new text"},
            "insert_line": {"type": "integer", "description": "insert: after this line"},
            "view_range": {"type": "array", "items": {"type": "integer"}, "description": "view: [start, end], end -1 = to the end"},
        },
        "required": ["command", "path"],
    }

    async def execute(self, *, command: Any = None, path: Any = None, **kwargs: Any) -> str:  # type: ignore[override]
        if not command:
            raise ToolError("Parameter `command` is required: view, create, str_replace, insert or undo_edit.")
        if not path:
            raise ToolError(f"Parameter `path` is required for `{command}`: give the absolute path of the file.")
        resolved, note = resolve_path(str(path), str(command))
        operator = self._get_operator()
        if command == "create" and await operator.exists(resolved) and not await operator.is_directory(resolved):
            if kwargs.get("file_text") is None:
                raise ToolError("Parameter `file_text` is required for command: create")
            old = await operator.read_file(resolved)
            await operator.write_file(resolved, kwargs["file_text"])
            self._file_history[str(resolved)].append(old)  # undo_edit restores what was there
            return self._noted(f"File overwritten at: {resolved} (the previous content can be restored with undo_edit)", note)
        if command == "create" and not resolved.parent.exists():
            resolved.parent.mkdir(parents=True, exist_ok=True)
        if command == "view" and resolved.is_dir():
            listing = list_directory(resolved)
            return self._noted(f"Here's the files and directories up to 2 levels deep in {resolved}, excluding hidden items:\n{listing}\n", note)
        if command == "view" and kwargs.get("view_range"):
            kwargs["view_range"] = await self._clamp_range(resolved, kwargs["view_range"], operator)
        if command == "str_replace" and kwargs.get("old_str") is not None:
            loose = await self._loose_replace(resolved, kwargs["old_str"], kwargs.get("new_str"), operator)
            if loose is not None:
                return self._noted(loose, note)
        result = await super().execute(command=command, path=str(resolved), **kwargs)
        return self._noted(result, note)

    def _make_output(self, file_content: str, file_descriptor: str, init_line: int = 1, expand_tabs: bool = True) -> str:
        # A file's final newline ends its last line; it does not start another.
        # Live 2026-10-03: 37 lines were shown as 38 (the last one empty), and
        # SYRAX reported 38 and fought a phantom blank line while deleting.
        if file_content.endswith("\n"):
            file_content = file_content[:-1]
        return super()._make_output(file_content, file_descriptor, init_line, expand_tabs)

    @staticmethod
    def _noted(text: str, note: Optional[str]) -> str:
        return f"{note}\n{text}" if note else str(text)

    async def _clamp_range(self, path: Path, view_range: Any, operator: Any) -> Any:
        if not isinstance(view_range, list) or len(view_range) != 2 or await operator.is_directory(path):
            return view_range
        try:
            start, end = int(view_range[0]), int(view_range[1])
        except (TypeError, ValueError):
            return view_range
        n = len((await operator.read_file(path)).split("\n"))
        start = min(max(1, start), n)
        if end != -1 and (end > n or end < start):
            end = -1 if end > n else start
        return [start, end]

    async def _loose_replace(self, path: Path, old: str, new: Optional[str], operator: Any) -> Optional[str]:
        """None when the exact text is there (the normal path handles it).
        Otherwise replace a single whitespace-tolerant match, or raise an error
        that shows the nearest lines."""
        if await operator.is_directory(path):
            return None
        content = (await operator.read_file(path)).expandtabs()
        old_x = old.expandtabs()
        if old_x in content:
            return None
        hits = find_loose(content, old_x)
        lines = content.split("\n")
        if len(hits) == 1:
            i = hits[0]
            n_old = len(old_x.strip("\n").split("\n"))
            replacement = reindent((new or "").expandtabs(), old_x, lines[i])
            new_lines = lines[:i] + replacement.split("\n") + lines[i + n_old:]
            await operator.write_file(path, "\n".join(new_lines))
            self._file_history[str(path)].append(content)
            snippet = "\n".join(f"{k + 1:6}\t{lines_k}" for k, lines_k in enumerate(new_lines) if i - 3 <= k <= i + n_old + 3)
            return (f"The file {path} has been edited (old_str matched at line {i + 1} once whitespace was ignored; "
                    f"new_str was re-indented to match).\n{snippet}\nReview the changes and make sure they are as expected.")
        first = old_x.strip("\n").split("\n")[0].strip()
        near = [f"{k + 1}: {ln}" for k, ln in enumerate(lines) if first and first in ln][:5]
        where = (" Lines that contain its first line: " + " | ".join(near)) if near else ""
        many = f" It matches {len(hits)} places when whitespace is ignored; include more surrounding lines." if len(hits) > 1 else ""
        raise ToolError(f"No replacement was performed: old_str did not appear verbatim in {path}.{many}{where} "
                        "View the file and copy the exact text, including indentation.")
