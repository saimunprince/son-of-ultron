"""A file's final newline ends its last line (live 2026-10-03: a 37-line file
was shown, and counted by SYRAX, as 38)."""

import asyncio

from syrax.editor import SyraxEditor


def view(path, **kw):
    return asyncio.run(SyraxEditor().execute(command="view", path=str(path), **kw))


def test_view_shows_exactly_the_lines_a_file_has(tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("".join(f"line {i}\n" for i in range(1, 38)), newline="\n")
    out = view(f)
    assert "    37\tline 37" in out and "    38" not in out
    g = tmp_path / "old.log"
    g.write_text("stale\n", newline="\n")
    assert "     1\tstale" in view(g) and "     2" not in view(g)
    h = tmp_path / "no_newline.txt"
    h.write_text("a\nb", newline="\n")
    assert "     2\tb" in view(h)
    k = tmp_path / "blank_last.txt"
    k.write_text("a\n\n", newline="\n")  # a real empty last line stays visible
    assert "     2\t" in view(k) and "     3" not in view(k)


def test_the_editor_says_how_to_delete_a_file():
    assert "os.remove" in SyraxEditor().description
