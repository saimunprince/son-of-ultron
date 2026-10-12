"""Tidy a folder (the Desktop by default): sort its loose files into folders by type or by month, and undo it.

Prebuilt SYRAX skill (feature catalog: organize_desktop); the idea came from
the surveyed JARVIS assistants, the code is SYRAX's own. A preview is the
default: nothing moves until action=organize. Nothing is overwritten (a name
clash gets " (1)"), shortcuts stay where they are, and every move is written
to a manifest in the folder so action=undo puts each file back. It
deletes nothing, not even its own empty folders, so it stays at WRITE level.
"""

import asyncio
import datetime as dt
import json
import shutil
import time
from pathlib import Path
from typing import ClassVar, Dict, List, Optional

from app.tool.base import BaseTool, ToolResult

KINDS = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".ico", ".tif", ".tiff"},
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md", ".rtf", ".odt", ".csv"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"},
    "Music": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".java", ".c", ".cpp", ".cs", ".php", ".sh", ".ps1"},
    "Installers": {".exe", ".msi"},
}
KEEP = {".lnk", ".url", ".ini"}  # shortcuts and desktop.ini stay where they are
MANIFEST = ".syrax-organize-"


def default_folder() -> Path:
    return Path.home() / "Desktop"


def target_of(f: Path, by: str) -> str:
    if by == "month":
        return dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m")
    ext = f.suffix.lower()
    return next((k for k, exts in KINDS.items() if ext in exts), "Other")


def free_name(dest: Path) -> Path:
    if not dest.exists():
        return dest
    for n in range(1, 1000):
        cand = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        if not cand.exists():
            return cand
    raise FileExistsError(f"no free name for {dest.name}")


def plan(folder: Path, by: str) -> List[Dict[str, str]]:
    moves = []
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.suffix.lower() in KEEP or f.name.startswith(MANIFEST) or f.name.startswith("."):
            continue
        moves.append({"from": str(f), "to": str(folder / target_of(f, by) / f.name)})
    return moves


def organize(folder: Optional[str] = None, by: str = "type", apply: bool = False) -> str:
    root = Path(folder).expanduser() if folder else default_folder()
    if not root.is_dir():
        raise FileNotFoundError(f"no folder at {root}")
    if by not in ("type", "month"):
        raise ValueError("by must be type or month")
    moves = plan(root, by)
    if not moves:
        return f"{root} has no loose files to sort."
    groups: Dict[str, int] = {}
    for m in moves:
        groups[Path(m["to"]).parent.name] = groups.get(Path(m["to"]).parent.name, 0) + 1
    summary = ", ".join(f"{n} to {g}" for g, n in sorted(groups.items()))
    if not apply:
        return f"Preview for {root}: {len(moves)} file(s) would move: {summary}. Nothing moved; call action=organize to do it."
    done = []
    for m in moves:
        dest = free_name(Path(m["to"]))
        dest.parent.mkdir(exist_ok=True)
        shutil.move(m["from"], str(dest))
        done.append({"from": m["from"], "to": str(dest)})
    manifest = root / f"{MANIFEST}{time.strftime('%Y%m%d-%H%M%S')}.json"
    manifest.write_text(json.dumps(done, indent=1), encoding="utf-8")
    return f"Moved {len(done)} file(s) in {root}: {summary}. manifest: {manifest} (action=undo puts them back)."


def undo(folder: Optional[str] = None, manifest: Optional[str] = None) -> str:
    root = Path(folder).expanduser() if folder else default_folder()
    path = Path(manifest) if manifest else max(root.glob(f"{MANIFEST}*.json"), default=None, key=lambda p: p.name)
    if path is None or not Path(path).is_file():
        raise FileNotFoundError("no organize manifest to undo")
    moves = json.loads(Path(path).read_text(encoding="utf-8"))
    back = 0
    for m in reversed(moves):
        src, dest = Path(m["to"]), Path(m["from"])
        if src.exists() and not dest.exists():
            shutil.move(str(src), str(dest))
            back += 1
    Path(path).rename(Path(str(path) + ".undone"))  # nothing is deleted: the skill stays at WRITE level
    return (f"Put back {back} of {len(moves)} file(s) from {Path(path).name}. "
            "The folders it made are left in place (empty ones can be deleted by hand).")


class Skill(BaseTool):
    name: ClassVar[str] = "organize_folder"
    description: ClassVar[str] = ("Tidy a folder (default: the Desktop) by sorting its loose files into folders by type or by month. "
                                  "action=preview shows what would move (nothing moves); action=organize moves them and writes a "
                                  "manifest; action=undo puts the last organize back. Shortcuts stay; nothing is overwritten.")
    risk: ClassVar[str] = "WRITE"
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["preview", "organize", "undo"]},
            "folder": {"type": "string", "description": "folder to tidy (default: the Desktop)"},
            "by": {"type": "string", "enum": ["type", "month"], "description": "sort by file type (default) or by month"},
            "manifest": {"type": "string", "description": "for undo: a specific manifest file (default: the newest)"},
        },
        "required": ["action"],
    }

    async def execute(self, action: str, folder: Optional[str] = None, by: str = "type", manifest: Optional[str] = None) -> ToolResult:
        try:
            if action == "undo":
                return ToolResult(output=await asyncio.to_thread(undo, folder, manifest))
            if action in ("preview", "organize"):
                return ToolResult(output=await asyncio.to_thread(organize, folder, by or "type", action == "organize"))
            return ToolResult(error="action must be preview, organize or undo")
        except Exception as e:
            return ToolResult(error=f"organize_folder: {e}")
