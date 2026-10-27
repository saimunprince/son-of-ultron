"""Quality run #88 (guard_broad_delete): desktop find_files with target "*" read the star as a letter and answered
"No files matching '*'" in a folder that held keep.txt; SYRAX then told the human the folder was already empty. A
target with *, ? or [ is a wildcard pattern on the whole name; a plain word is still a part of the name."""

import asyncio

from syrax.desktop import DesktopControl


def find(target, folder):
    return asyncio.run(DesktopControl().execute(action="find_files", target=target, folder=str(folder))).output


def test_a_star_lists_every_file(tmp_path):
    (tmp_path / "keep.txt").write_text("still here\n")
    (tmp_path / "notes.md").write_text("x")
    out = find("*", tmp_path)
    assert "keep.txt" in out and "notes.md" in out and "No files matching" not in out


def test_a_pattern_matches_whole_names_and_a_word_still_matches_a_part(tmp_path):
    for n in ("keep.txt", "notes.md", "report_2026.TXT"):
        (tmp_path / n).write_text("x")
    out = find("*.txt", tmp_path)
    assert "keep.txt" in out and "report_2026.TXT" in out and "notes.md" not in out
    assert "report_2026.TXT" in find("report", tmp_path)
    assert "No files matching" in find("*.pdf", tmp_path)
