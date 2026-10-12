"""wallpaper: reads and sets through SystemParametersInfoW (faked here, so the
real desktop is never changed), only for existing images, and reports the
wallpaper it replaced."""

import asyncio
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("prebuilt_wallpaper_skill", Path(__file__).with_name("skill.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class FakeDesktop:
    def __init__(self, current="C:\\Windows\\Web\\Wallpaper\\Windows\\img0.jpg"):
        self.current, self.calls = current, []

    def __call__(self, action, path=None):
        self.calls.append((action, path))
        if action == mod.SPI_GETDESKWALLPAPER:
            return self.current
        self.current = path
        return path


def run(**kw):
    return asyncio.run(mod.Skill().execute(**kw))


def test_get_and_set_report_the_old_wallpaper(monkeypatch, tmp_path):
    desk = FakeDesktop()
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_spi", desk)
    assert run(action="get").output == "The wallpaper is C:\\Windows\\Web\\Wallpaper\\Windows\\img0.jpg."
    img = tmp_path / "night.png"
    img.write_bytes(b"\x89PNG\r\n")
    out = run(action="set", path=str(img)).output
    assert out.startswith(f"Wallpaper set to {img.resolve()}") and "it was C:\\Windows\\Web\\Wallpaper\\Windows\\img0.jpg" in out
    assert desk.calls[-1] == (mod.SPI_SETDESKWALLPAPER, str(img.resolve()))


def test_only_existing_images_are_used(monkeypatch, tmp_path):
    desk = FakeDesktop()
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_spi", desk)
    assert "no image file" in run(action="set", path=str(tmp_path / "missing.jpg")).error
    doc = tmp_path / "notes.txt"
    doc.write_text("x")
    assert "is not an image" in run(action="set", path=str(doc)).error
    assert "no image file" in run(action="set").error
    assert all(a == mod.SPI_GETDESKWALLPAPER for a, _ in desk.calls)  # nothing was set


def test_other_systems_are_told_plainly(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    assert "only supported on Windows" in run(action="get").error


def test_the_skill_declares_what_it_does():
    s = mod.Skill()
    assert s.name == "wallpaper" and s.risk == "SYSTEM"
