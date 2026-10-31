"""scene: "coding mode", "research mode", "chill mode" set up the computer for one kind of work in one request.

From the Ultron comparison of 2026-10-31 (its workspace presets); the code is SYRAX's own. Like undo, the tool does not
act: it names the scene's steps as the exact desktop calls, and the brain makes them through the normal path, so each
step is permission-checked and journaled like any other call, and volume, dark mode and the rest stay undoable.

The owner's scenes live in backend/config/scenes.json ({"name": {"triggers": [...], "steps": [{"action", "target",
"value"}]}}); a scene there replaces the built-in one of the same name. Only desktop actions in STEP_ACTIONS are
allowed as steps: opening, launching, volume, media, window and dark mode, never typing, clicking or trashing."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.tool.base import BaseTool, ToolResult
from syrax.journal import BACKEND_ROOT

SCENES_FILE = BACKEND_ROOT / "config" / "scenes.json"
STEP_ACTIONS = {"open", "launch_app", "volume", "media", "window", "dark_mode"}

BUILT_IN: Dict[str, dict] = {
    "coding": {"triggers": ["coding", "code korbo", "kaj korbo", "কোডিং", "কোড করব"],
               "steps": [{"action": "launch_app", "target": "Visual Studio Code"}, {"action": "launch_app", "target": "Terminal"},
                         {"action": "dark_mode", "value": "on"}, {"action": "volume", "value": "35"}]},
    "research": {"triggers": ["research", "study", "porbo", "porashona", "পড়াশোনা", "পড়ব", "গবেষণা"],
                 "steps": [{"action": "open", "target": "https://arxiv.org"}, {"action": "open", "target": "https://scholar.google.com"},
                           {"action": "volume", "value": "25"}]},
    "chill": {"triggers": ["chill", "relax", "movie", "gaan", "music", "বিশ্রাম", "গান"],
              "steps": [{"action": "open", "target": "https://www.youtube.com/results?search_query=lofi+hip+hop"},
                        {"action": "volume", "value": "55"}]},
}


def _valid(scene: Any) -> Optional[dict]:
    if not isinstance(scene, dict) or not isinstance(scene.get("steps"), list):
        return None
    steps = [{k: str(s[k]) for k in ("action", "target", "value") if s.get(k) is not None}
             for s in scene["steps"] if isinstance(s, dict) and s.get("action") in STEP_ACTIONS]
    if not steps:
        return None
    return {"triggers": [str(t) for t in scene.get("triggers") or [] if str(t).strip()], "steps": steps}


def load(path: Optional[Path] = None) -> Dict[str, dict]:
    """Built-in scenes, with the owner's file laid over them; a broken file or entry is skipped, never fatal."""
    out = {k: dict(v) for k, v in BUILT_IN.items()}
    try:
        own = json.loads(Path(path or SCENES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        own = {}
    for name, scene in (own.items() if isinstance(own, dict) else []):
        if (v := _valid(scene)) is not None:
            out[str(name).lower()] = v
    return out


def match(request: str, scenes: Dict[str, dict]) -> Optional[str]:
    """The scene a request names: its name, or the longest of its triggers found in the request."""
    text = (request or "").lower()
    if text.strip() in scenes:
        return text.strip()
    best = None
    for name, scene in scenes.items():
        for word in [name, *scene["triggers"]]:
            if re.search(rf"(?<!\w){re.escape(word.lower())}(?!\w)", text) and (best is None or len(word) > best[1]):
                best = (name, len(word))
    return best[0] if best else None


class SceneTool(BaseTool):
    name: str = "scene"
    description: str = (
        "Set the computer up for a kind of work in one go: 'coding mode', 'research mode', 'chill mode' or a scene the owner "
        "saved. Shows the scene's steps as exact `desktop` calls; then make each call yourself, in order. "
        "Without a request it lists the scenes. This tool changes nothing."
    )
    parameters: dict = {
        "type": "object",
        "properties": {"request": {"type": "string", "description": "The scene's name, or the human's words, e.g. 'coding mode'."}},
        "required": [],
    }

    async def execute(self, request: str = "") -> ToolResult:
        scenes = load()
        if not (request or "").strip():
            return ToolResult(output="Scenes: " + "; ".join(
                f"{n} ({', '.join(s['triggers'][:3]) or 'no triggers'})" for n, s in sorted(scenes.items()))
                + f". The owner's own scenes go in {SCENES_FILE}.")
        name = match(request, scenes)
        if name is None:
            return ToolResult(error=f"No scene matches {request!r}. Scenes: {', '.join(sorted(scenes))}.")
        lines = [f"Scene {name}: make exactly these calls, in order, then say what each did:"]
        lines += [f"{i}. call `desktop` with {json.dumps(s, ensure_ascii=False)}" for i, s in enumerate(scenes[name]["steps"], 1)]
        return ToolResult(output="\n".join(lines))
