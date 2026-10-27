"""Crash recovery reads an edited file as UTF-8, the encoding the editor (app/tool/file_operators.py) writes.
On this machine the locale is cp1252 (utf8_mode 0): a default read decoded an em dash as mojibake, so an
interrupted str_replace that had landed was UNCERTAIN and a create that had landed was PARTIAL, and an
autonomous task waited for a human."""

from syrax.journal import Journal

NL = chr(10)
NEW = 'title = "SYRAX — সিরাক্স"' + NL


def edit(path, **args):
    return {"name": "str_replace_editor", "args": {"path": str(path), **args}}


def test_an_applied_str_replace_with_non_ascii_new_str_is_completed(tmp_path):
    j = Journal(tmp_path / "j.db")
    f = tmp_path / "m.py"
    op = edit(f, command="str_replace", old_str="title = 1" + NL, new_str=NEW)
    f.write_bytes(("title = 1" + NL + "b = 2" + NL).encode("utf-8"))
    assert j.verify_operation(op)["state"] == "NOT_STARTED"
    f.write_bytes((NEW + "b = 2" + NL).encode("utf-8"))
    v = j.verify_operation(op)
    assert v["state"] == "COMPLETED" and v["checks"]["new_present"] is True


def test_an_applied_create_with_non_ascii_text_is_completed(tmp_path):
    j = Journal(tmp_path / "j.db")
    f = tmp_path / "c.py"
    f.write_bytes(NEW.encode("utf-8"))
    v = j.verify_operation(edit(f, command="create", file_text=NEW))
    assert v["state"] == "COMPLETED" and v["checks"]["content_matches"] is True
