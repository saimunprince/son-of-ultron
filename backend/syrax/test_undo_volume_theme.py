"""Undo (feature catalog), the Ultron comparison of 2026-10-31: undo reversed brightness, wallpaper, the Windows theme,
a sorted folder and file edits, but not a volume change, and not GNOME's dark mode (its answer did not say what it was
before). A volume change now says the level before it, dark mode on Linux says the scheme before it, and undo names
the exact call that puts each back."""

import asyncio

from syrax import desktop, linuxinput, undo


def test_volume_and_linux_dark_mode_name_their_reverse():
    v = undo.reverse_of("desktop", {"action": "volume", "value": "80"}, "Volume 35% -> 80%.")
    assert v["reverse"] == {"tool": "desktop", "args": {"action": "volume", "value": "35"}}
    assert undo.reverse_of("desktop", {"action": "volume", "value": "get"}, "Volume 35%.") is None
    assert undo.reverse_of("desktop", {"action": "volume", "value": "80"}, "Volume 80% -> 80%.") is None
    m = undo.reverse_of("desktop", {"action": "volume", "value": "mute"}, "Volume 35% (muted), it was not muted.")
    assert m["reverse"] == {"tool": "desktop", "args": {"action": "volume", "value": "unmute"}}
    d = undo.reverse_of("desktop", {"action": "dark_mode", "value": "on"}, "Dark mode turned on (it was off).")
    assert d["reverse"] == {"tool": "desktop", "args": {"action": "dark_mode", "value": "off"}}
    assert undo.reverse_of("desktop", {"action": "dark_mode", "value": "on"}, "Dark mode turned on (it was on).") is None


def test_linux_volume_reports_the_level_before(monkeypatch):
    state = {"level": 0.35, "muted": False}

    async def fake_run(*args, **kw):
        if args[:2] == ("wpctl", "get-volume"):
            return 0, f"Volume: {state['level']:.2f}{' [MUTED]' if state['muted'] else ''}", ""
        if args[:2] == ("wpctl", "set-volume"):
            state["level"] = int(args[-1].rstrip("%")) / 100
        if args[:2] == ("wpctl", "set-mute"):
            state["muted"] = args[-1] == "1"
        return 0, "", ""

    monkeypatch.setattr(desktop, "_run", fake_run)
    monkeypatch.setattr(desktop, "WINDOWS", False)
    monkeypatch.setattr(desktop, "MACOS", False)
    monkeypatch.setattr(desktop.shutil, "which", lambda n: "/usr/bin/" + n if n == "wpctl" else None)
    tool = desktop.DesktopControl()
    assert asyncio.run(tool._do_volume("80")).output == "Volume 35% -> 80%."
    assert asyncio.run(tool._do_volume("get")).output == "Volume 80%."
    assert asyncio.run(tool._do_volume("mute")).output == "Volume 80% (muted), it was not muted."


def test_gnome_dark_mode_says_what_it_was(monkeypatch):
    calls = []

    class R:
        stdout = "'default'"

    def fake(cmd, **kw):
        calls.append(cmd)
        return R()

    monkeypatch.delenv("SYRAX_NO_REAL_INPUT", raising=False)
    monkeypatch.setattr(linuxinput.subprocess, "run", fake)
    assert linuxinput.dark_mode("on") == "Dark mode turned on (it was off)."
    assert calls[-1][-1] == "prefer-dark"


def _trash(home, original, name):
    files, info = home / "Trash" / "files", home / "Trash" / "info"
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    (files / name).write_text("data")
    from urllib.parse import quote
    (info / f"{name}.trashinfo").write_text(f"[Trash Info]\nPath={quote(str(original))}\nDeletionDate=2026-10-31T10:00:00\n")


def test_a_trashed_file_names_untrash_and_untrash_puts_it_back(tmp_path, monkeypatch):
    r = undo.reverse_of("desktop", {"action": "trash", "target": "/home/p/a b.txt"},
                        "Moved /home/p/a b.txt to the Recycle Bin; restore it from there if it was a mistake.")
    assert r["reverse"] == {"tool": "desktop", "args": {"action": "untrash", "target": "/home/p/a b.txt"}}
    original = tmp_path / "work" / "a b.txt"
    original.parent.mkdir()
    _trash(tmp_path / "share", original, "a b.txt")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(desktop, "WINDOWS", False)
    out = asyncio.run(desktop.DesktopControl()._do_untrash(str(original)))
    assert out.output.startswith("Restored") and original.read_text() == "data"
    assert not (tmp_path / "share" / "Trash" / "info" / "a b.txt.trashinfo").exists()
    again = asyncio.run(desktop.DesktopControl()._do_untrash(str(original)))
    assert again.error and "not in the trash" in again.error


def test_untrash_never_overwrites(tmp_path, monkeypatch):
    original = tmp_path / "a.txt"
    original.write_text("new")
    _trash(tmp_path / "share", original, "a.txt")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(desktop, "WINDOWS", False)
    out = asyncio.run(desktop.DesktopControl()._do_untrash(str(original)))
    assert out.error and "already exists" in out.error and original.read_text() == "new"
