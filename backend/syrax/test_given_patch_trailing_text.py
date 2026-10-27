"""Review 2026-10-27: diff_changed_lines kept a hunk open across a blank line, so the human's words after the diff
("...\n\n- do not rewrite it") counted as a removed line, and the human's own diff given to apply_patch never matched
the given patch: it was always refused. A hunk ends when the lengths its @@ header states are used up."""

from syrax.agent import diff_changed_lines, given_patch
from syrax.test_bridge import call, script  # noqa: F401  (script is a fixture)
from syrax.test_given_patch import DIFF, fake_tools, run_task

AFTER = "Apply exactly this patch with apply_patch:\n" + DIFF + "\n- do not rewrite it\n- report the result honestly\n"
TWO = ("--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,3 @@\n x = 1\n\n-y = 2\n+y = 3\n"
       "--- a/b.py\n+++ b/b.py\n@@ -0,0 +1 @@\n+print('b')\n\nThanks!\n- one more note")


def test_words_after_the_diff_are_not_its_lines():
    assert given_patch(AFTER)["lines"] == diff_changed_lines(DIFF) == ["-# This line is not in the file", "+# SYRAX probe"]


def test_a_blank_context_line_stays_inside_its_hunk():
    assert diff_changed_lines(TWO) == ["-y = 2", "+y = 3", "+print('b')"]


def test_the_humans_own_diff_is_applied_when_words_follow_it(script, monkeypatch):
    ran = fake_tools(monkeypatch)
    task, texts, _ = run_task(script, AFTER, [call("apply_patch", {"diff": DIFF})])
    assert ran == ["apply_patch"] and not texts[0].startswith("Error: refused: the human gave this patch")
