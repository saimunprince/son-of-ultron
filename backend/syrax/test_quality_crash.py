"""Live 2026-10-15: research_report's task wrote "78.37 \u00b0C" with
python_execute, whose open() writes cp1252 on Windows; the checker read the
file as UTF-8, raised UnicodeDecodeError, and the whole quality run died
without an outcome in the journal (the autonomy cycle then took the core).
The checker reads the task's file in the encoding it was written in, and an
error inside one case's check fails that case, not the run."""

import asyncio

from syrax import quality
from syrax.journal import Journal
from syrax.quality import QualityRunner
from syrax.test_quality_busy import Core


def test_a_file_written_in_the_windows_code_page_is_read(tmp_path):
    p = tmp_path / "ethanol.md"
    p.write_bytes("Boiling point: 78.37 \u00b0C".encode("cp1252"))
    assert quality._text(str(p)) == "Boiling point: 78.37 \u00b0C"
    p.write_bytes("Boiling point: 78.37 \u00b0C".encode("utf-8"))
    assert quality._text(str(p)) == "Boiling point: 78.37 \u00b0C"


def test_a_checker_error_fails_its_case_not_the_run(tmp_path):
    j = Journal(tmp_path / "j.db")
    report = tmp_path / "ws" / "r.md"
    report.parent.mkdir(parents=True)
    report.write_bytes("78.37 \u00b0C".encode("cp1252"))
    cases = [
        {"id": "bad_check", "prompt": "17*23?", "checks": [{"kind": "file_regex", "path": str(report), "pattern": "(unclosed"}]},
        {"id": "file_ok", "prompt": "17*23?", "checks": [{"kind": "file_regex", "path": str(report), "pattern": r"78\.37 \u00b0C"}]},
        {"id": "arith", "prompt": "17*23?", "checks": [{"kind": "final_regex", "pattern": r"\b391\b"}]},
    ]
    row = asyncio.run(QualityRunner(Core(j), j, workspace=tmp_path / "ws")._run(None, cases, None))
    by = {r["id"]: r for r in row["results"]}
    assert not by["bad_check"]["ok"] and "error" in by["bad_check"]["checks"][0]["detail"].lower()
    assert by["file_ok"]["ok"] and by["arith"]["ok"] and j.quality_runs(limit=1)[0]["id"] == row["id"]
