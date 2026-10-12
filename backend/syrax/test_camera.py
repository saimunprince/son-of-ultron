"""The webcam (feature catalog): one frame, released at once, saved in the
workspace, journaled and shown to the brain; never in SYRAX's own work. A fake
camera stands in, so no real camera is ever opened here."""

import asyncio
import base64

import pytest

from syrax import camera, permissions
from syrax.desktop import DesktopControl
from syrax.test_bridge import get_journal, script  # noqa: F401


class FakeCV2:
    CAP_DSHOW = 700

    def __init__(self, opened=True, frames=True):
        self.opened, self.frames, self.released, self.reads = opened, frames, False, 0

    def VideoCapture(self, index, backend):
        self.index, self.backend = index, backend
        return self

    def isOpened(self):
        return self.opened

    def read(self):
        self.reads += 1
        return (True, "frame") if self.frames else (False, None)

    def imencode(self, ext, frame):
        class Buf:
            def tobytes(self):
                return b"PNG-" + frame.encode()
        return True, Buf()

    def release(self):
        self.released = True


def test_one_frame_after_warmup_and_always_released():
    cv = FakeCV2()
    assert camera.capture(0, warmup=5, cv2=cv) == b"PNG-frame" and cv.reads == 6 and cv.released
    for bad in (FakeCV2(opened=False), FakeCV2(frames=False)):
        with pytest.raises(RuntimeError):
            camera.capture(0, cv2=bad)
        assert bad.released  # never left open


def test_the_desktop_camera_saves_journals_and_shows_the_photo(script, tmp_path, monkeypatch):
    import types

    import syrax.desktop as desktop

    monkeypatch.setattr(camera, "capture", lambda index=0: b"PNG-frame")
    monkeypatch.setattr(desktop, "config", types.SimpleNamespace(workspace_root=tmp_path))
    out = asyncio.run(DesktopControl().execute(action="camera"))
    assert out.error is None and out.output.startswith("Took one photo with the camera: ")
    saved = out.output.split(": ", 1)[1]
    assert base64.b64decode(out.base64_image) == b"PNG-frame" and open(saved, "rb").read() == b"PNG-frame"
    ev = [e for e in get_journal().recent_events(20) if e["type"] == "camera.captured"]
    assert ev and ev[-1]["payload"]["path"] == saved


def test_a_missing_camera_is_an_error_and_own_work_may_not_use_it(monkeypatch):
    def none(index=0):
        raise RuntimeError("no camera found, or another app is using it")

    monkeypatch.setattr(camera, "capture", none)
    out = asyncio.run(DesktopControl().execute(action="camera"))
    assert out.error == "camera: no camera found, or another app is using it"
    d = permissions.classify("desktop", {"action": "camera"})
    assert d.level == permissions.SYSTEM and permissions.decide(d, "autonomous", "look at me").action == "refuse"
