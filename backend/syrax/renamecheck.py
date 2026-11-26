"""Rename check (2026-11-26): quality case deep_rename_api, live with several brains: the agent renamed the def and
some call sites, left `from geo.core import calc_area, calc_perimeter` in report.py, and finished claiming success.
Model-independent: when an edit renames a function or class (a `def old(` / `class Old` replaced by another name), or
the request says "rename X to Y", the files of that project are searched for whole-word uses of the old name that
are still there, and the brain is told which file:line, right after the edit and once more before the task ends.

Cheap on purpose: .git, virtual environments, node_modules, caches, binary and big files are skipped, the walk and
the hits are capped. A line that keeps the old name as an alias of the new one (`old = new`, `new as old`) is not a
leftover: a request may ask for exactly that."""

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", "dist", "build", ".idea", ".vscode", "site-packages", ".syrax"}
TEXT_EXT = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".kt", ".go", ".rs", ".rb", ".php",
            ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift", ".scala", ".lua", ".sh", ".ps1", ".toml", ".cfg",
            ".ini", ".json", ".yaml", ".yml", ".md", ".rst", ".txt", ".html", ".vue", ".svelte"}
MAX_FILES = 2000         # files looked at in one search
MAX_FILE_BYTES = 512_000  # bigger files are skipped
MAX_HITS = 12            # leftover lines named to the brain
MARKERS = (".git", "pyproject.toml", "setup.py", "setup.cfg", "package.json")

# a definition in Python, JS/TS or a class in most languages
_DEF = re.compile(r"^\s*(?:async\s+)?(?:def|class|function)\s+([A-Za-z_]\w*)", re.M)
_GOAL = re.compile(r"\brename\s+(?:the\s+)?(?:function\s+|class\s+|method\s+|symbol\s+|variable\s+)?[`'\"]?([A-Za-z_]\w*)"
                   r"(?:\(\))?[`'\"]?\s+(?:to|as|into)\s+[`'\"]?([A-Za-z_]\w*)", re.I)
_WORDS = {"it", "this", "that", "them", "the", "file", "files", "folder", "function", "class", "method", "all"}

LEFTOVER_NOTE = ("\n(SYRAX rename check: `{old}` was renamed to `{new}`, and these lines in {root} still use `{old}`:\n"
                 "{lines}\nUpdate each one that should use `{new}`; keep `{old}` only where the request asks for it "
                 "(for example an alias for old callers). The rename is not finished until then.)")
RENAME_NUDGE = ("[SYRAX check, not a new request] The rename is not finished: these lines still use the old name.\n"
                "{notes}\nUpdate them (keep the old name only where the request asks for it, such as an alias), run "
                "the tests if there are any, then give the final answer. Do not say it is done before that.")


def _names(text: str) -> List[str]:
    return _DEF.findall(text or "")


def renames_in(old_text: str, new_text: str) -> List[Tuple[str, str]]:
    """(old, new) for each definition `old_text` had that `new_text` no longer has, paired in order with a definition
    `new_text` added; [] when the counts do not pair up (a deletion, a new function, a move)."""
    before, after = _names(old_text), _names(new_text)
    gone = [n for n in before if n not in after]
    added = [n for n in after if n not in before]
    if not gone or len(gone) != len(added):
        return []
    return [(o, n) for o, n in zip(gone, added) if len(o) >= 3]


def goal_renames(goal: str) -> List[Tuple[str, str]]:
    """The "rename X to Y" pairs the request states in its own words."""
    out = []
    for o, n in _GOAL.findall(goal or ""):
        if o.lower() not in _WORDS and n.lower() not in _WORDS and o != n and len(o) >= 3 and (o, n) not in out:
            out.append((o, n))
    return out


def _diff_sides(section: str) -> Tuple[str, str]:
    old, new = [], []
    for line in section.split("\n"):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("-"):
            old.append(line[1:])
        elif line.startswith("+"):
            new.append(line[1:])
    return "\n".join(old), "\n".join(new)


def edit_renames(name: str, args: Any) -> List[Tuple[Path, str, str]]:
    """(edited file, old, new) for the renames a str_replace_editor str_replace or an apply_patch made."""
    a = args if isinstance(args, dict) else {}
    out: List[Tuple[Path, str, str]] = []
    if name == "str_replace_editor" and a.get("command") == "str_replace":
        path = edited_paths(name, a)
        if path:
            out += [(path[0], o, n) for o, n in renames_in(str(a.get("old_str") or ""), str(a.get("new_str") or ""))]
    elif name == "apply_patch":
        from syrax.selfedit import diff_paths, file_sections, work_root

        for section in file_sections(str(a.get("diff") or "")):
            paths = diff_paths(section)
            if not paths:
                continue
            old, new = _diff_sides(section)
            out += [(work_root() / paths[-1], o, n) for o, n in renames_in(old, new)]
    return out


def edited_paths(name: str, args: Any) -> List[Path]:
    """The files a str_replace_editor edit or an apply_patch wrote; [] when they cannot be told."""
    a = args if isinstance(args, dict) else {}
    try:
        if name == "str_replace_editor" and a.get("command") in ("create", "str_replace", "insert") and a.get("path"):
            from syrax import editor

            path = editor.resolve_path(str(a.get("path")), str(a.get("command")))[0]
            return [editor.redirect(Path(os.path.realpath(path)))]
        if name == "apply_patch":
            from syrax.selfedit import diff_paths, work_root

            return [work_root() / p for p in diff_paths(str(a.get("diff") or ""))]
    except Exception:  # an unresolvable path: the edit itself already said so
        return []
    return []


def project_root(path: Path) -> Path:
    """The folder a rename's uses live in: above the topmost Python package that holds `path` (geo_proj for
    geo_proj/geo/core.py), or the file's own folder; that folder's parent instead when the parent is a project
    (a marker such as .git or pyproject.toml) and the folder is not."""
    d = path if path.is_dir() else path.parent
    while (d / "__init__.py").is_file() and d.parent != d:
        d = d.parent
    if not any((d / m).exists() for m in MARKERS) and d.parent != d and any((d.parent / m).exists() for m in MARKERS):
        d = d.parent
    return d


def _alias(line: str, old: str, new: str) -> bool:
    o, n = re.escape(old), re.escape(new)
    return bool(re.search(rf"\b{o}\s*(?::[^=]*)?=\s*(?:[\w.]+\.)?{n}\b", line) or re.search(rf"\b{n}\s+as\s+{o}\b", line)
                or re.search(rf"\b(?:const|let|var)\s+{o}\s*=\s*(?:[\w.]+\.)?{n}\b", line))


def _files(root: Path) -> Iterable[Path]:
    seen = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info"))
        for f in sorted(files):
            p = Path(base) / f
            if p.suffix.lower() not in TEXT_EXT:
                continue
            seen += 1
            if seen > MAX_FILES:
                return
            yield p


def leftovers(root: Path, old: str, new: str, limit: int = MAX_HITS) -> List[str]:
    """`file:line: text` for each line under `root` that still uses `old` as a whole word (aliases of `new` left out)."""
    word = re.compile(rf"(?<![\w$]){re.escape(old)}(?![\w$])")
    hits: List[str] = []
    for p in _files(root):
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096] or old.encode() not in data:
            continue
        text = data.decode("utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if word.search(line) and not _alias(line, old, new):
                rel = p.relative_to(root).as_posix() if p.is_relative_to(root) else str(p)
                hits.append(f"{rel}:{i}: {line.strip()[:160]}")
                if len(hits) >= limit:
                    return hits
    return hits


def note_for(renames: Dict[Tuple[str, str], Path]) -> str:
    """LEFTOVER_NOTE for each recorded rename with old uses left; "" when there are none."""
    notes = []
    for (old, new), root in list(renames.items())[:4]:
        lines = leftovers(root, old, new)
        if lines:
            notes.append(LEFTOVER_NOTE.format(old=old, new=new, root=root, lines="\n".join(f"  {x}" for x in lines)))
    return "".join(notes)


class RenameWatch:
    """The renames of one task: recorded from its edits (and the request's own words), checked after each edit and at
    the end. Never fails a call: anything unexpected only leaves the note out."""

    def __init__(self, goal: str = "", goal_dirs: Optional[List[str]] = None):
        self.goal_pairs = goal_renames(goal)
        self.renames: Dict[Tuple[str, str], Path] = {}
        self.asked = False
        for raw in goal_dirs or []:
            p = Path(raw)
            if self.goal_pairs and p.exists():
                for pair in self.goal_pairs:
                    self.renames.setdefault(pair, project_root(p) if p.is_file() else p)

    def after_edit(self, name: str, args: Any) -> str:
        """The note for the observation of a successful edit ("" for none)."""
        try:
            for path, old, new in edit_renames(name, args):
                self.renames[(old, new)] = project_root(path)
            if self.goal_pairs:
                for path in edited_paths(name, args)[:1]:
                    for pair in self.goal_pairs:
                        self.renames[pair] = project_root(path)
            return note_for(self.renames) if self.renames else ""
        except Exception:
            return ""

    def final_nudge(self) -> Optional[str]:
        """RENAME_NUDGE once per task while old uses remain; None otherwise."""
        if self.asked or not self.renames:
            return None
        try:
            notes = note_for(self.renames)
        except Exception:
            return None
        if not notes:
            return None
        self.asked = True
        return RENAME_NUDGE.format(notes=notes.strip())
