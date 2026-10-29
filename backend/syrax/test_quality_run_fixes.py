"""First Linux quality runs, 2026-10-29: two failures were SYRAX's.
- self_patch_edit: the brain's diff headed its hunk with a bare "@@"; apply_patch refused "no @@ hunks", though its
  content locator never uses the line numbers. A bare "@@" now starts a hunk.
- deep_log_triage: the right answer ("E204 9") ended with "[terminate status=success]", a tool call written as text, and
  the 60-character answer was 78. Such a note is stripped like the console notes."""

from syrax.agent import without_console_notes
from syrax.selfedit import apply_by_content, parse_hunks

LIVE_DIFF = "--- a/backend/syrax/reminders.py\n+++ b/backend/syrax/reminders.py\n@@\n-    MAX_TEXT = 300\n+    MAX_TEXT = 400\n"


def test_a_bare_hunk_header_is_a_hunk():
    assert parse_hunks(LIVE_DIFF) == [[("-", "    MAX_TEXT = 300"), ("+", "    MAX_TEXT = 400")]]
    assert len(parse_hunks("@@ def f():\n-a\n+b\n")) == 1  # "@@ section title" too


def test_the_live_diff_now_applies_by_content(tmp_path):
    f = tmp_path / "reminders.py"
    f.write_text('"""doc"""\n\nMAX_TEXT = 300\n\n\ndef f():\n    return MAX_TEXT\n', encoding="utf-8")
    out = apply_by_content(LIVE_DIFF, f)
    assert isinstance(out, tuple), out
    text, placed = out
    assert placed == 1 and "MAX_TEXT = 400\n" in text and "    MAX_TEXT = 400" not in text  # the file's own indent kept


def test_a_terminate_written_as_text_is_stripped():
    live = "E204 9\n\nThere are no strings on me. Task complete.\n\n[terminate status=success]"
    out = without_console_notes(live)
    assert "[terminate" not in out and out.startswith("E204 9") and len(out) <= 60


def test_a_deeper_indented_file_gets_the_new_line_at_its_own_depth(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("class A:\n    def f(self):\n        return 1\n", encoding="utf-8")
    text, placed = apply_by_content("--- a/m.py\n+++ b/m.py\n@@\n-return 1\n+return 2\n", f)
    assert placed == 1 and "        return 2\n" in text
