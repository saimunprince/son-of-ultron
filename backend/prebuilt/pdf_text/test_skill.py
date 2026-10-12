"""pdf_text: reads page text, ranges and the page count of a real PDF made here
with fpdf2; bad paths, non-PDFs and impossible ranges are errors."""

import asyncio
import importlib.util
from pathlib import Path

from fpdf import FPDF

_spec = importlib.util.spec_from_file_location("prebuilt_pdf_text_skill", Path(__file__).with_name("skill.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def make_pdf(path: Path, pages):
    pdf = FPDF()
    pdf.set_title("Test Report")
    pdf.set_font("Helvetica", size=12)
    for text in pages:
        pdf.add_page()
        pdf.cell(0, 10, text)
    pdf.output(str(path))


def run(**kw):
    return asyncio.run(mod.Skill().execute(**kw))


def test_reads_all_pages_and_a_range(tmp_path):
    f = tmp_path / "report.pdf"
    make_pdf(f, ["Alpha page one", "Beta page two", "Gamma page three"])
    out = run(path=str(f)).output
    assert out.startswith("report.pdf: 3 page(s), title 'Test Report'; showing pages 1-3")
    assert "--- page 2 ---\nBeta page two" in out and "Gamma page three" in out
    part = run(path=str(f), first=2, last=2).output
    assert "Beta page two" in part and "Alpha" not in part and "showing pages 2-2" in part


def test_long_text_is_cut_and_says_where_to_continue(tmp_path, monkeypatch):
    f = tmp_path / "long.pdf"
    make_pdf(f, ["x" * 60, "y" * 60, "z" * 60])
    monkeypatch.setattr(mod, "MAX_CHARS", 50)
    out = asyncio.run(mod.Skill().execute(path=str(f)))
    text = mod.read_pdf(str(f), max_chars=50)
    assert "ask for" in text and out.error is None


def test_bad_inputs_are_errors(tmp_path):
    assert "no file" in run(path=str(tmp_path / "none.pdf")).error
    doc = tmp_path / "notes.txt"
    doc.write_text("x")
    assert "is not a PDF" in run(path=str(doc)).error
    f = tmp_path / "one.pdf"
    make_pdf(f, ["only"])
    assert "outside 1-1" in run(path=str(f), first=3).error


def test_the_skill_declares_what_it_does():
    s = mod.Skill()
    assert s.name == "pdf_text" and s.risk == "READ_ONLY" and s.parameters["required"] == ["path"]
