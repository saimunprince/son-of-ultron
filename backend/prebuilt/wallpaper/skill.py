"""Show or change the desktop wallpaper (Windows).

Prebuilt SYRAX skill; the idea comes from the JARVIS assistants surveyed on
2026-10-12, the code is SYRAX's own. Only an existing local image is used (no
download), and a change reports the wallpaper it replaced so it can be put back.
"""

import asyncio
import sys
from pathlib import Path
from typing import ClassVar, Optional

from app.tool.base import BaseTool, ToolResult

SPI_GETDESKWALLPAPER, SPI_SETDESKWALLPAPER = 0x0073, 0x0014
SPIF_UPDATEINIFILE, SPIF_SENDCHANGE = 0x01, 0x02
IMAGES = {".jpg", ".jpeg", ".png", ".bmp"}


def _spi(action: int, path: Optional[str] = None) -> str:
    """SystemParametersInfoW: read the current wallpaper path, or set one."""
    import ctypes

    user32 = ctypes.windll.user32
    if action == SPI_GETDESKWALLPAPER:
        buf = ctypes.create_unicode_buffer(520)
        if not user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, len(buf), buf, 0):
            raise OSError("Windows did not report the wallpaper")
        return buf.value
    if not user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, path, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE):
        raise OSError("Windows refused the wallpaper")
    return path or ""


def wallpaper(action: str = "get", path: Optional[str] = None) -> str:
    if sys.platform != "win32":
        raise RuntimeError("wallpaper is only supported on Windows for now")
    action = (action or "get").lower()
    before = _spi(SPI_GETDESKWALLPAPER) or "(none)"
    if action == "get":
        return f"The wallpaper is {before}."
    if action != "set":
        raise ValueError("action must be get or set")
    image = Path(str(path or "")).expanduser()
    if not str(path or "").strip() or not image.is_file():
        raise FileNotFoundError(f"no image file at {path!r}")
    if image.suffix.lower() not in IMAGES:
        raise ValueError(f"{image.name} is not an image ({', '.join(sorted(IMAGES))})")
    _spi(SPI_SETDESKWALLPAPER, str(image.resolve()))
    return f"Wallpaper set to {image.resolve()} (it was {before}; to undo, set it back to that)."


class Skill(BaseTool):
    name: ClassVar[str] = "wallpaper"
    description: ClassVar[str] = ("Show (get) or change (set) the desktop wallpaper to an existing local image "
                                  "(.jpg, .png, .bmp). A change reports the old wallpaper so it can be undone.")
    risk: ClassVar[str] = "SYSTEM"
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get", "set"], "description": "get the current wallpaper, or set one"},
            "path": {"type": "string", "description": "full path of a local image, for set"},
        },
        "required": ["action"],
    }

    async def execute(self, action: str = "get", path: Optional[str] = None) -> ToolResult:
        try:
            return ToolResult(output=await asyncio.to_thread(wallpaper, action, path))
        except Exception as e:
            return ToolResult(error=f"wallpaper: {e}")
