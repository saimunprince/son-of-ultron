"""organize_folder: a preview moves nothing; organize sorts loose files by type
or month without overwriting and leaves shortcuts; undo puts every file back.
A temporary folder stands in for the Desktop."""

import asyncio
import importlib.util
import json
import os
from pathlib import Path

_spec = importlib.util.spec_from_file_location("prebuilt_organize_skill", Path(__file__).with_name("skill.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def desk(tmp_path):
    d = tmp_path / "Desktop"
    d.mkdir()
    for name in ("photo.jpg", "notes.txt", "report.pdf", "song.mp3", "tool.py", "weird.xyz", "Chrome.lnk", "desktop.ini"):
        (d / name).write_text(name)
    (d / "Projects").mkdir()
    (d / "Images").mkdir()
    (d / "Images" / "photo.jpg").write_text("older photo")
    return d


def run(**kw):
    return asyncio.run(mod.Skill().execute(**kw))


def test_preview_moves_nothing(tmp_path):
    d = desk(tmp_path)
    out = run(action="preview", folder=str(d)).output
    assert out.startswith(f"Preview for {d}: 6 file(s) would move") and "Nothing moved" in out
    assert (d / "notes.txt").exists() and not (d / "Documents").exists()


def test_organize_by_type_keeps_shortcuts_and_never_overwrites(tmp_path):
    d = desk(tmp_path)
    out = run(action="organize", folder=str(d)).output
    assert out.startswith(f"Moved 6 file(s) in {d}") and "manifest:" in out
    assert (d / "Documents" / "notes.txt").exists() and (d / "Documents" / "report.pdf").exists()
    assert (d / "Music" / "song.mp3").exists() and (d / "Code" / "tool.py").exists() and (d / "Other" / "weird.xyz").exists()
    assert (d / "Images" / "photo (1).jpg").read_text() == "photo.jpg" and (d / "Images" / "photo.jpg").read_text() == "older photo"
    assert (d / "Chrome.lnk").exists() and (d / "desktop.ini").exists() and (d / "Projects").is_dir()


def test_undo_puts_every_file_back(tmp_path):
    d = desk(tmp_path)
    run(action="organize", folder=str(d))
    out = run(action="undo", folder=str(d)).output
    assert out.startswith("Put back 6 of 6 file(s)")
    for name in ("photo.jpg", "notes.txt", "report.pdf", "song.mp3", "tool.py", "weird.xyz"):
        assert (d / name).exists(), name
    assert not any((d / "Documents").iterdir()) and (d / "Images" / "photo.jpg").read_text() == "older photo"
    assert not list(d.glob(".syrax-organize-*.json")) and list(d.glob(".syrax-organize-*.json.undone"))
    assert "no organize manifest" in run(action="undo", folder=str(d)).error


def test_by_month_and_bad_input(tmp_path):
    d = tmp_path / "f"
    d.mkdir()
    f = d / "a.txt"
    f.write_text("x")
    os.utime(f, (1_700_000_000, 1_700_000_000))  # 2023-11
    run(action="organize", folder=str(d), by="month")
    assert (d / "2023-11" / "a.txt").exists()
    assert "no folder" in run(action="preview", folder=str(tmp_path / "missing")).error
    assert "type or month" in run(action="preview", folder=str(d), by="size").error


def test_the_skill_declares_what_it_does():
    s = mod.Skill()
    assert s.name == "organize_folder" and s.risk == "WRITE" and s.parameters["required"] == ["action"]
