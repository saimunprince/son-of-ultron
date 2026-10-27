"""Tabs stay tabs: str_replace and insert change only what they replace, and undo_edit restores the exact bytes
(2026-10-27 review: upstream expandtabs'd the whole file on every edit, so a Makefile's recipes lost their tabs)."""

import asyncio
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

import pytest  # noqa: E402

from syrax import editor as ed  # noqa: E402
from syrax.editor import SyraxEditor  # noqa: E402

MAKEFILE = (b"all: build\n\nbuild:\n\tgo build ./...\n\tgo vet ./...\n\n"
            b"test:\n\tgo test ./...\n\nrows:\n\tprintf 'a\\tb\\tc\\n' > rows.tsv\n")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def tool(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(ed, "BACKEND_ROOT", tmp_path / "repo" / "backend")
    monkeypatch.setattr(ed, "WORKSPACE", tmp_path / "repo" / "backend" / "workspace")
    (tmp_path / "repo" / "backend" / "workspace").mkdir(parents=True)
    t = SyraxEditor()
    t._file_history.clear()
    return t


@pytest.fixture
def makefile(tmp_path):
    f = tmp_path / "Makefile"
    f.write_bytes(MAKEFILE)
    return f


def test_replacing_one_recipe_line_keeps_every_other_tab(tool, makefile):
    run(tool.execute(command="str_replace", path=str(makefile), old_str="\tgo vet ./...", new_str="\tstaticcheck ./..."))
    assert makefile.read_bytes() == MAKEFILE.replace(b"\tgo vet ./...", b"\tstaticcheck ./...")
    run(tool.execute(command="undo_edit", path=str(makefile)))
    assert makefile.read_bytes() == MAKEFILE


def test_old_str_copied_from_view_with_spaces_still_splices_into_the_tabbed_file(tool, makefile):
    # view shows a tab as spaces, so the model sends spaces
    run(tool.execute(command="str_replace", path=str(makefile), old_str="        go vet ./...", new_str="\tstaticcheck ./..."))
    assert makefile.read_bytes() == MAKEFILE.replace(b"\tgo vet ./...", b"\tstaticcheck ./...")
    run(tool.execute(command="undo_edit", path=str(makefile)))
    assert makefile.read_bytes() == MAKEFILE


def test_a_match_inside_a_tab_touches_only_its_own_line(tool, makefile):
    run(tool.execute(command="str_replace", path=str(makefile), old_str="  go vet ./...", new_str="  go vet -v ./..."))
    lines = makefile.read_bytes().split(b"\n")
    assert lines[4].strip() == b"go vet -v ./..."
    others = [ln for k, ln in enumerate(MAKEFILE.split(b"\n")) if k != 4]
    assert [ln for k, ln in enumerate(lines) if k != 4] == others


def test_a_reindented_match_keeps_the_files_tabs(tool, makefile):
    run(tool.execute(command="str_replace", path=str(makefile),
                     old_str="  go build ./...\n  go vet ./...", new_str="  gofmt -l .\n  go vet ./..."))
    assert makefile.read_bytes() == MAKEFILE.replace(b"\tgo build ./...", b"\tgofmt -l .")
    run(tool.execute(command="undo_edit", path=str(makefile)))
    assert makefile.read_bytes() == MAKEFILE


def test_insert_keeps_every_tab_and_undo_restores_the_bytes(tool, makefile):
    run(tool.execute(command="insert", path=str(makefile), insert_line=8, new_str="\tgo test -race ./..."))
    assert makefile.read_bytes() == MAKEFILE.replace(b"\tgo test ./...\n", b"\tgo test ./...\n\tgo test -race ./...\n")
    run(tool.execute(command="undo_edit", path=str(makefile)))
    assert makefile.read_bytes() == MAKEFILE


def test_splice_expanded_maps_offsets_back_to_the_raw_text():
    from syrax.editor import splice_expanded

    raw = "a\tb\n\tc\td\n"
    x = raw.expandtabs()
    s = x.index("c")
    assert splice_expanded(raw, s, s + 1, "C") == "a\tb\n\tC\td\n"
