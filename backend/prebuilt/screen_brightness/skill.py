"""Read or set the built-in display's brightness (Windows, through WMI).

Prebuilt SYRAX skill; the idea comes from the JARVIS assistants surveyed on
2026-10-12, the code is SYRAX's own. A set always reports the level it
replaced, so it can be put back. External monitors usually do not expose WMI
brightness; that is reported as such, never as success.
"""

import asyncio
import subprocess
import sys
from typing import ClassVar, Optional

from app.tool.base import BaseTool, ToolResult

GET = "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop | Select-Object -First 1).CurrentBrightness"
SET = ("Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop | "
       "Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={level}}} | Out-Null")
UNSUPPORTED = "this display does not expose brightness to Windows (usually an external monitor); nothing changed"


def powershell(command: str, timeout: float = 20.0) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, text=True, timeout=timeout)


def current() -> int:
    r = powershell(GET)
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out.isdigit():
        raise RuntimeError(UNSUPPORTED)
    return int(out)


def brightness(action: str = "get", level: Optional[int] = None) -> str:
    if sys.platform != "win32":
        raise RuntimeError("screen brightness is only supported on Windows for now")
    action = (action or "get").lower()
    before = current()
    if action == "get":
        return f"Screen brightness is {before}%."
    if action != "set":
        raise ValueError("action must be get or set")
    if level is None:
        raise ValueError("set needs a level from 0 to 100")
    target = max(0, min(int(level), 100))
    r = powershell(SET.format(level=target))
    if r.returncode != 0:
        raise RuntimeError(UNSUPPORTED)
    after = current()
    return f"Screen brightness {before}% -> {after}% (to undo, set it to {before})."


class Skill(BaseTool):
    name: ClassVar[str] = "screen_brightness"
    platforms: ClassVar[tuple] = ("win32",)  # Windows code only: never offered as a tool elsewhere (skills.platform_problem)
    description: ClassVar[str] = ("Read (get) or change (set, 0-100) the brightness of this computer's built-in screen. "
                                  "A set reports the old level so it can be undone.")
    risk: ClassVar[str] = "SYSTEM"
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get", "set"], "description": "get the level, or set it"},
            "level": {"type": "integer", "description": "brightness percent for set, 0-100"},
        },
        "required": ["action"],
    }

    async def execute(self, action: str = "get", level: Optional[int] = None) -> ToolResult:
        try:
            return ToolResult(output=await asyncio.to_thread(brightness, action, level))
        except Exception as e:
            return ToolResult(error=f"screen_brightness: {e}")
