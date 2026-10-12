"""One frame from the webcam, taken only when the human asks ("look at me").

From the feature catalog (webcam), approved by the owner on 2026-10-12
(opencv-python-headless 4.14.0.94). Every use is journaled as
`camera.captured` and shown in the UI; the camera is opened for a single frame
and released at once, never kept open or watched. The desktop tool's `camera`
action is SYSTEM level, so SYRAX's own (autonomous) work may not use it.
"""

from __future__ import annotations

import sys
from typing import Any, Optional

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
