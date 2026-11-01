"""Audit 2026-11-01 (integrations I-01, I-10, confirmed): undo after creating a NEW file named undo_edit, which said
"undone successfully" and left the file in place; and a Windows dark-mode switch to the same mode was listed as
undoable. A new file is undone by moving it to the trash (asked first, restorable); a no-op switch is not listed."""

from syrax import undo


def test_a_new_file_is_undone_by_trashing_it_and_an_overwrite_by_undo_edit():
    new = undo.reverse_of("str_replace_editor", {"command": "create", "path": "/w/a.txt", "file_text": "hi"},
                          "File created successfully at: /w/a.txt")
    assert new["reverse"] == {"tool": "desktop", "args": {"action": "trash", "target": "/w/a.txt"}}
    over = undo.reverse_of("str_replace_editor", {"command": "create", "path": "/w/a.txt", "file_text": "hi"},
                           "File overwritten at: /w/a.txt (the previous content can be restored with undo_edit)")
    assert over["reverse"] == {"tool": "str_replace_editor", "args": {"command": "undo_edit", "path": "/w/a.txt"}}


def test_a_same_mode_windows_switch_is_not_undoable():
    assert undo.reverse_of("desktop", {"action": "dark_mode", "value": "on"},
                           "Windows switched from dark to dark mode (to undo, switch it back to dark).") is None


def test_untrash_is_offered_only_where_it_works(monkeypatch):
    out = "Moved /w/a.txt to the Recycle Bin; restore it from there if it was a mistake."
    monkeypatch.setattr(undo.sys, "platform", "win32")
    assert undo.reverse_of("desktop", {"action": "trash", "target": "/w/a.txt"}, out) is None
    monkeypatch.setattr(undo.sys, "platform", "linux")
    assert undo.reverse_of("desktop", {"action": "trash", "target": "/w/a.txt"}, out)["reverse"]["args"]["action"] == "untrash"
