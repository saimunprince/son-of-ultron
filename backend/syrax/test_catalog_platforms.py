"""Audit 2026-11-01 (docs D7, integrations I-08): Windows-only features (window control, display off, click by sight,
brightness, wallpaper) showed as HAVE with no platform, on Linux too, and dark mode and autostart still said Windows
only. Each feature carries its platforms, the catalog shows them, and on_this_platform answers for this machine."""

from syrax import catalog


def by_id(fid):
    return next(f for f in catalog.CATALOG if f.id == fid)


def test_windows_only_features_say_so_and_are_not_here_on_linux():
    for fid in ("windows", "display_sleep", "click_by_sight", "brightness", "wallpaper"):
        f = by_id(fid)
        assert f.platforms == ("win32",) and not catalog.on_this_platform(f, "linux") and catalog.on_this_platform(f, "win32")
    assert catalog.on_this_platform(by_id("dark_mode"), "linux") and not catalog.on_this_platform(by_id("dark_mode"), "darwin")
    assert catalog.on_this_platform(by_id("volume_media"), "darwin")  # no platforms: everywhere


def test_the_rendered_catalog_has_a_platforms_column():
    text = catalog.render()
    assert "| Feature | Status | Platforms |" in text and "| Windows |" in text and "| all |" in text
    assert "Temperature is not measured yet" not in text and "Start at login" in text
