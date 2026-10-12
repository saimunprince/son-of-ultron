"""Undo (feature catalog): the history is read from the tool calls the journal
already records, each reversible call names its exact reverse, a later call
that is that reverse marks it undone, and the undo tool itself changes nothing."""

import asyncio

from syrax import permissions, undo
from syrax.journal import Journal

OBS = "Observed output of cmd `{tool}` executed:\n"


def call(j, t, cid, name, args, output):
    j.record_sync("tool.started", {"id": cid, "name": name, "args": args}, task_id=t)
    j.record_sync("tool.completed", {"id": cid, "name": name, "ok": True, "output": OBS.format(tool=name) + output}, task_id=t)


def task(j, text="x"):
    return j.start_task_sync(text)


def test_reversible_calls_name_their_reverse():
    assert undo.reverse_of("screen_brightness", {"action": "set", "level": 70},
                           "Screen brightness 40% -> 70% (to undo, set it to 40).")["reverse"] == {
        "tool": "screen_brightness", "args": {"action": "set", "level": 40}}
    w = undo.reverse_of("wallpaper", {"action": "set", "path": "C:/new.png"},
                        "Wallpaper set to C:/new.png (it was C:/Windows/img0.jpg; to undo, set it back to that).")
    assert w["reverse"]["args"] == {"action": "set", "path": "C:/Windows/img0.jpg"}
    d = undo.reverse_of("desktop", {"action": "dark_mode", "value": "on"},
                        "Windows switched from light to dark mode (to undo, switch it back to light).")
    assert d["reverse"]["args"] == {"action": "dark_mode", "value": "off"}
    e = undo.reverse_of("str_replace_editor", {"command": "create", "path": "C:/x/a.txt", "file_text": "hi"}, "File created")
    assert e["reverse"] == {"tool": "str_replace_editor", "args": {"command": "undo_edit", "path": "C:/x/a.txt"}}
    assert undo.reverse_of("str_replace_editor", {"command": "view", "path": "C:/x/a.txt"}, "") is None
    assert undo.reverse_of("screen_brightness", {"action": "get"}, "Screen brightness is 40%.") is None
    assert undo.reverse_of("wallpaper", {"action": "set", "path": "a"}, "Wallpaper set to a (it was (none); to undo...") is None
    o = undo.reverse_of("organize_folder", {"action": "organize"},
                        "Moved 6 file(s) in C:/Users/p/Desktop: 2 to Documents. manifest: C:/Users/p/Desktop/.syrax-organize-1.json (action=undo puts them back).")
    assert o["reverse"] == {"tool": "organize_folder", "args": {"action": "undo", "folder": "C:/Users/p/Desktop",
                                                                 "manifest": "C:/Users/p/Desktop/.syrax-organize-1.json"}}
    assert undo.reverse_of("organize_folder", {"action": "preview"}, "Preview for x: 2 file(s) would move") is None


def test_the_newest_pending_comes_first_and_a_reverse_marks_it_done(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = task(j)
    call(j, t, "c1", "screen_brightness", {"action": "set", "level": 70}, "Screen brightness 40% -> 70% (to undo, set it to 40).")
    call(j, t, "c2", "desktop", {"action": "dark_mode", "value": "on"}, "Windows switched from light to dark mode (to undo...).")
    labels = [r["label"] for r in undo.pending(j)]
    assert labels == ["Windows light -> dark mode", "screen brightness 40% -> 70%"]
    t2 = task(j, "undo that")
    call(j, t2, "c3", "desktop", {"action": "dark_mode", "value": "off"}, "Windows switched from dark to light mode (to undo...).")
    labels = [r["label"] for r in undo.pending(j)]
    assert labels[0] == "Windows dark -> light mode" and "Windows light -> dark mode" not in labels  # undone (and itself undoable)
    assert "screen brightness 40% -> 70%" in labels


def test_the_tool_only_tells_and_its_level_is_read_only(tmp_path):
    j = Journal(tmp_path / "j.db")
    tool = undo.UndoTool(journal_provider=lambda: j)
    assert asyncio.run(tool.execute()).output.startswith("Nothing to undo")
    t = task(j)
    call(j, t, "c1", "str_replace_editor", {"command": "str_replace", "path": "C:/w/a.py", "old_str": "a", "new_str": "b"}, "edited")
    out = asyncio.run(tool.execute()).output
    assert 'call `str_replace_editor` with {"command": "undo_edit", "path": "C:/w/a.py"}' in out
    assert permissions.level_of_tool("undo") == permissions.READ_ONLY
