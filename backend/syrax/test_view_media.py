"""2026-11-04: the human could drop a picture on SYRAX, but no tool showed it to the brain; and on Wayland SYRAX kept
trying `window list`, which can never work there."""

import asyncio
import base64
import io
import shutil
import subprocess

import pytest
from PIL import Image

from syrax import desktop, permissions
from syrax.desktop import DesktopControl


def run(**kw):
    return asyncio.run(DesktopControl().execute(**kw))


def test_an_image_is_shown_to_the_brain_scaled_down(tmp_path):
    p = tmp_path / "photo.png"
    Image.new("RGB", (4000, 2000), "red").save(p)
    out = run(action="view", target=str(p))
    assert out.error is None and "4000x2000" in out.output
    shown = Image.open(io.BytesIO(base64.b64decode(out.base64_image)))
    assert max(shown.size) == desktop.VIEW_MAX_SIDE


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_a_video_is_shown_as_six_frames(tmp_path):
    p = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10", "-y", str(p)], check=True)
    out = run(action="view", target=str(p))
    assert out.error is None and "six frames" in out.output and "of 0:03" in out.output
    grid = Image.open(io.BytesIO(base64.b64decode(out.base64_image)))
    assert grid.size == (640 * 3, 480 * 2)


def test_what_cannot_be_shown_says_why(tmp_path):
    assert "needs the path" in run(action="view").error
    assert "No file" in run(action="view", target=str(tmp_path / "gone.png")).error
    (tmp_path / "notes.txt").write_text("hi")
    assert "not an image or a video" in run(action="view", target=str(tmp_path / "notes.txt")).error


def test_viewing_is_read_only():
    assert permissions.classify("desktop", {"action": "view", "target": "/tmp/x.png"}).level == permissions.READ_ONLY


@pytest.mark.skipif(desktop.WINDOWS, reason="Linux and macOS only")
def test_window_control_off_windows_says_once_not_to_try_again(monkeypatch):
    monkeypatch.setattr(desktop, "front_window", lambda: "'Notes' (gedit)")
    out = run(action="window", value="list")
    assert "do not try it again" in out.error and "In front now: 'Notes' (gedit)" in out.error
    assert "In front now" not in run(action="window", value="focus", target="Notes").error


def test_the_camera_borrows_a_frame_from_the_hud_that_holds_it(monkeypatch):
    # live 2026-11-04: "can you see me?" -> "camera: no camera found, or another app is using it" while the HUD showed him
    from syrax import camera
    from syrax.core import get_core

    def busy(index=0):
        raise RuntimeError("no camera found, or another app is using it")

    jpeg = io.BytesIO()
    Image.new("RGB", (64, 48), "blue").save(jpeg, format="JPEG")
    sent = []

    async def hud(event):
        sent.append(event)
        if event.get("type") == "camera_frame_request":
            assert not camera.hud_frame(event["id"], "")  # a HUD with its camera off does not answer for the others
            assert camera.hud_frame(event["id"], base64.b64encode(jpeg.getvalue()).decode())

    monkeypatch.setattr(camera, "capture", busy)
    monkeypatch.setattr(get_core(), "broadcast", hud)
    out = run(action="camera")
    assert out.error is None and "the camera the HUD shows" in out.output and out.output.endswith(".jpg")
    assert base64.b64decode(out.base64_image) == jpeg.getvalue()


def test_no_hud_frame_keeps_the_plain_camera_error(monkeypatch):
    from syrax import camera
    from syrax.core import get_core

    def busy(index=0):
        raise RuntimeError("no camera found, or another app is using it")

    async def silent(event):
        pass

    monkeypatch.setattr(camera, "capture", busy)
    monkeypatch.setattr(camera, "HUD_TIMEOUT_S", 0.05)
    monkeypatch.setattr(get_core(), "broadcast", silent)
    out = asyncio.run(DesktopControl().execute(action="camera"))
    assert "another app is using it" in out.error and not camera._waiting
