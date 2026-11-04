"""One frame from the webcam, taken only when the human asks ("look at me").

From the feature catalog (webcam), approved by the owner on 2026-10-12
(opencv-python-headless 4.14.0.94). Every use is journaled as
`camera.captured` and shown in the UI; the camera is opened for a single frame
and released at once, never kept open or watched. The desktop tool's `camera`
action is SYSTEM level, so SYRAX's own (autonomous) work may not use it.
"""

from __future__ import annotations

import asyncio
import base64
import sys
import uuid
from typing import Any, Dict, Optional

WARMUP_FRAMES = 5  # the first frames of many webcams are dark


def capture(index: int = 0, warmup: int = WARMUP_FRAMES, cv2: Optional[Any] = None) -> bytes:
    """A PNG of one frame from camera `index`."""
    if cv2 is None:
        import cv2  # noqa: F811  (opencv-python-headless)
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else 0
    cap = cv2.VideoCapture(index, backend)
    try:
        if not cap.isOpened():
            raise RuntimeError("no camera found, or another app is using it")
        ok, frame = False, None
        for _ in range(max(1, warmup + 1)):
            ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError("the camera gave no picture")
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            raise RuntimeError("could not encode the picture")
        return bytes(buf.tobytes())
    finally:
        cap.release()


# ——— the HUD's camera (2026-11-04) ———
# The HUD keeps the camera open for hand tracking, and then nothing else can open it: asked "can you see me?", the
# camera action failed with "another app is using it". The HUD then gives one frame of what it already shows.
HUD_TIMEOUT_S = 3.0
HUD_MAX_CHARS = 4_000_000
_waiting: Dict[str, "asyncio.Future"] = {}


async def from_hud(broadcast, timeout: Optional[float] = None) -> Optional[bytes]:
    """One JPEG frame from the camera the HUD shows, or None (no HUD, or its camera is off)."""
    rid = uuid.uuid4().hex[:12]
    fut = asyncio.get_running_loop().create_future()
    _waiting[rid] = fut
    try:
        await broadcast({"type": "camera_frame_request", "id": rid})
        data = await asyncio.wait_for(fut, HUD_TIMEOUT_S if timeout is None else timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        _waiting.pop(rid, None)
    try:
        return base64.b64decode(data, validate=True)
    except (ValueError, TypeError):
        return None


def hud_frame(rid: str, data: str) -> bool:
    """A HUD's answer to from_hud; an empty one (its camera is off) is ignored, so another HUD may still answer."""
    fut = _waiting.get(str(rid or ""))
    if fut is None or fut.done() or not data or len(data) > HUD_MAX_CHARS:
        return False
    fut.set_result(data)
    return True
