"""Quality runs #15 and #17 (2026-11-01, self_patch_edit): the brain pasted the editor's numbered view into its diff
("     27\\tCHECK_EVERY_S = 15.0") and apply_patch refused it. Numbers on every context and removed line are taken off;
a diff that does not carry them on every such line is left as written."""

from syrax.selfedit import strip_view_numbers

NUMBERED = """--- a/backend/syrax/reminders.py
+++ b/backend/syrax/reminders.py
@@ -27,3 +27,3 @@
     27\tCHECK_EVERY_S = 15.0
-    28\tMAX_TEXT = 300
+MAX_TEXT = 400
     29\tMAX_AHEAD_S = 366 * 86400
"""

CLEAN = """--- a/backend/syrax/reminders.py
+++ b/backend/syrax/reminders.py
@@ -27,3 +27,3 @@
 CHECK_EVERY_S = 15.0
-MAX_TEXT = 300
+MAX_TEXT = 400
 MAX_AHEAD_S = 366 * 86400
"""


def test_viewer_numbers_are_taken_off():
    assert strip_view_numbers(NUMBERED) == CLEAN


def test_a_diff_without_them_on_every_line_is_untouched():
    assert strip_view_numbers(CLEAN) == CLEAN
    mixed = CLEAN.replace(" CHECK_EVERY_S", "    27\tCHECK_EVERY_S")
    assert strip_view_numbers(mixed) == mixed
