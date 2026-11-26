"""Rename check (2026-11-26, quality deep_rename_api): an edit that renames a function or class, or a request that
says "rename X to Y", gets the file:line of every whole-word use of the old name still left in that project, after
the edit and once more before the task ends."""

import asyncio
import shutil
import uuid

import pytest

from syrax import quality, renamecheck as R
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401  (script is a fixture)


def geo_project(tmp_path):
    ws = tmp_path / "ws"
    case = next(c for c in quality._cases(ws) if c["id"] == "deep_rename_api")
    quality.prepare(case, ws)
    return case, ws / "deep" / "geo_proj"


def test_a_def_replaced_by_another_name_is_a_rename():
    assert R.renames_in("def calc_area(w, h):\n    return w * h\n", "def compute_area(w, h):\n    return w * h\n") == [
        ("calc_area", "compute_area")]
    assert R.renames_in("class OldThing:\n    pass", "class NewThing:\n    pass") == [("OldThing", "NewThing")]
    assert R.renames_in("async def fetch_all(x):", "async def load_all(x):") == [("fetch_all", "load_all")]
    assert R.renames_in("function oldName() {}", "function newName() {}") == [("oldName", "newName")]
    # a body change, a new function beside the old one, a deletion: no rename
    assert R.renames_in("def calc_area(w, h):\n    return w*h", "def calc_area(w, h):\n    return h*w") == []
    assert R.renames_in("def calc_area(w, h):", "def calc_area(w, h):\n\ndef other(x):") == []
    assert R.renames_in("def calc_area(w, h):\n    return 1", "") == []


def test_the_request_names_a_rename():
    assert R.goal_renames("Rename calc_area to compute_area in the geo package") == [("calc_area", "compute_area")]
    assert R.goal_renames("please rename the function `load` to `fetch_rows`") == [("load", "fetch_rows")]
    assert R.goal_renames("rename class Foo to Bar") == [("Foo", "Bar")]
    assert R.goal_renames("rename it to something better") == []
    assert R.goal_renames("What is the capital of Japan?") == []


def test_leftovers_name_file_and_line_and_spare_aliases(tmp_path):
    _, geo = geo_project(tmp_path)
    core = geo / "geo" / "core.py"
    core.write_text(core.read_text().replace("def calc_area(", "def compute_area(") + "\ncalc_area = compute_area\n")
    hits = R.leftovers(geo, "calc_area", "compute_area")
    assert hits and all(h.startswith("geo/report.py:") for h in hits)
    assert any("from geo.core import calc_area" in h for h in hits)
    assert R.project_root(core) == geo  # above the geo package, so tests/ and report.py are searched too
    report = geo / "geo" / "report.py"
    report.write_text(report.read_text().replace("calc_area", "compute_area"))
    assert R.leftovers(geo, "calc_area", "compute_area") == []  # only the alias is left, as the request asks


def test_the_search_is_whole_word_skips_junk_and_is_capped(tmp_path):
    (tmp_path / "a.py").write_text("calc_area_v2 = 1\nmy_calc_area = 2\nx = calc_area(1)\n")
    for junk in (".git", ".venv", "node_modules", "__pycache__"):
        (tmp_path / junk).mkdir()
        (tmp_path / junk / "b.py").write_text("calc_area()\n")
    (tmp_path / "blob.py").write_bytes(b"\0\0calc_area\0")
    (tmp_path / "big.py").write_text("calc_area\n" * 60_000)
    assert R.leftovers(tmp_path, "calc_area", "compute_area") == ["a.py:3: x = calc_area(1)"]
    (tmp_path / "many.py").write_text("calc_area()\n" * 50)
    assert len(R.leftovers(tmp_path, "calc_area", "compute_area")) == R.MAX_HITS


def test_the_watch_notes_leftovers_after_the_edit(tmp_path):
    _, geo = geo_project(tmp_path)
    core = geo / "geo" / "core.py"
    old = core.read_text()
    new = old.replace("def calc_area(", "def compute_area(")
    core.write_text(new)
    watch = R.RenameWatch("Fix the docs.")  # the request says nothing: the edit alone tells the rename
    note = watch.after_edit("str_replace_editor", {"command": "str_replace", "path": str(core), "old_str": old, "new_str": new})
    assert "SYRAX rename check" in note and "geo/report.py:" in note and "`compute_area`" in note
    assert watch.final_nudge() and watch.final_nudge() is None  # asked once
    report = geo / "geo" / "report.py"
    report.write_text(report.read_text().replace("calc_area", "compute_area"))
    assert R.RenameWatch("x").after_edit("str_replace_editor", {"command": "view", "path": str(core)}) == ""
    watch2 = R.RenameWatch("Rename calc_area to compute_area.")
    assert watch2.after_edit("str_replace_editor", {"command": "create", "path": str(report), "file_text": "x"}) == ""
    assert watch2.final_nudge() is None  # nothing left: no ask
    assert R.RenameWatch("x").after_edit("str_replace_editor", None) == ""  # never fails the call


def test_a_rename_the_request_names_is_checked_from_its_folder(tmp_path):
    _, geo = geo_project(tmp_path)
    watch = R.RenameWatch(f"Rename calc_area to compute_area in the package under {geo}.", [str(geo)])
    nudge = watch.final_nudge()
    assert nudge and "geo/core.py:" in nudge and "geo/report.py:" in nudge


def run_task(text):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind="conversation")
        await core.wait()
        return core.journal.task(tid)

    return asyncio.run(go())


@pytest.fixture
def geo_in_workspace(tmp_path):
    from syrax.editor import WORKSPACE

    _, src = geo_project(tmp_path)
    dest = WORKSPACE / f"_rename_check_{uuid.uuid4().hex[:8]}"
    shutil.copytree(src, dest)
    yield dest
    shutil.rmtree(dest, ignore_errors=True)


def test_a_task_that_leaves_old_uses_is_asked_once_to_finish(script, geo_in_workspace):
    geo = geo_in_workspace
    core = geo / "geo" / "core.py"
    report = geo / "geo" / "report.py"
    old = core.read_text()
    new = old.replace("def calc_area(", "def compute_area(")
    fixed = report.read_text().replace("calc_area", "compute_area")
    script.queue = [
        call("str_replace_editor", {"command": "str_replace", "path": str(core), "old_str": old, "new_str": new}),
        reply("Renamed calc_area to compute_area."),
        call("str_replace_editor", {"command": "create", "path": str(report), "file_text": fixed}),
        reply("Renamed it everywhere, report.py too."),
    ]
    task = run_task(f"Rename calc_area to compute_area in {geo}.")
    assert task["result"].endswith("report.py too.") and not script.queue
    seen = [str(m.content) for turn in script.seen for m in turn]
    assert any("SYRAX rename check" in s and "geo/report.py:" in s for s in seen)  # after the edit
    assert any("The rename is not finished" in s for s in seen)  # before the end
    assert "calc_area" not in report.read_text()
