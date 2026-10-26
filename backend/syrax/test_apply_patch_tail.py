"""2026-10-26: a refused hunk whose context and '-' lines are nowhere in the file gets the file's last lines in the
hint, not only the lines around its (guessed) @@ line. Journal, 30 days: 149 "does not apply cleanly" refusals; the
quality case self_patch_docs ("add the line `Probe line.` at the end of docs/EXECUTION_PLAN.md") failed 4 of 8 runs
because the brain invented the doc's head, was shown only lines 1-7, and never saw the end it had to append to. The
patch stays refused exactly as before; only the refusal says more."""

import re

import pytest

from syrax import selfedit
from syrax.test_devloop import git, repo

DOC = "docs/PLAN.md"
HEAD = f"--- a/{DOC}\n+++ b/{DOC}\n"
INVENTED = HEAD + "@@ -1,2 +1,3 @@\n # Execution Plan\n Initial setup.\n+Probe line.\n"


def commit(root, n):
    body = "".join(f"plan line {i}\n" for i in range(1, n + 1))
    (root / DOC).write_text(body, newline="\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "plan")
    return body


def refusal(diff, root):
    with pytest.raises(ValueError) as e:
        selfedit.apply_patch(diff, root, run=False)
    return str(e.value)


def numbered(msg):
    return [int(n) for n in re.findall(r"^\s*(\d+): plan line", msg, re.M)]


def test_invented_head_shows_the_head_and_the_real_tail_and_still_refuses(tmp_path):
    root = repo(tmp_path)
    body = commit(root, 40)
    msg = refusal(INVENTED, root)
    assert "does not apply cleanly" in msg and f"{DOC} has 40 lines; around line 1:" in msg  # the old hint, unchanged
    assert "    1: plan line 1" in msg and "    7: plan line 7" in msg
    assert f"... {DOC} ends at line 40 (" in msg and "line 1 is only its @@ header's guess" in msg
    assert numbered(msg) == list(range(1, 8)) + list(range(33, 41))  # head, then the last 8 lines, each once
    assert "content locator: " in msg and "old lines are not in the file" in msg  # still refused, for the same reason
    assert (root / DOC).read_text() == body


def test_the_diff_rebuilt_from_the_shown_tail_appends_at_the_end(tmp_path):
    root = repo(tmp_path)
    body = commit(root, 40)
    msg = refusal(INVENTED, root)
    tail = msg.split(f"... {DOC} ends at line 40", 1)[1]
    last = re.findall(r"^\s*\d+: (.*)$", tail, re.M)[-3:]
    rebuilt = HEAD + "@@ -38,3 +38,4 @@\n" + "".join(f" {l}\n" for l in last) + "+Probe line.\n"
    selfedit.apply_patch(rebuilt, root, run=False)
    assert (root / DOC).read_text() == body + "Probe line.\n"


def test_the_tail_is_not_repeated_when_the_lines_shown_already_reach_the_end(tmp_path):
    root = repo(tmp_path)
    commit(root, 12)
    msg = refusal(HEAD + "@@ -9,2 +9,3 @@\n # Execution Plan\n Initial setup.\n+Probe line.\n", root)
    assert f"{DOC} has 12 lines; around line 9:" in msg
    assert "ends at line" not in msg and numbered(msg) == list(range(3, 13))
    msg = refusal(INVENTED.replace("@@ -1,2 +1,3 @@", "@@ -3,2 +3,3 @@"), root)  # lines 1-9 shown: only 10-12 are added
    assert f"... {DOC} ends at line 12 (" in msg and numbered(msg) == list(range(1, 13))


def test_a_hunk_whose_lines_are_in_the_file_gets_no_tail(tmp_path):
    root = repo(tmp_path)
    (root / DOC).write_text("".join(f"x{i % 2}\n" for i in range(40)), newline="\n")  # every block occurs many times
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "twice")
    msg = refusal(HEAD + "@@ -1,2 +1,2 @@\n x0\n-x1\n+y\n", root)
    assert "ambiguous" in msg and f"{DOC} has 40 lines; around line 1:" in msg and "ends at line" not in msg


def test_the_tail_is_shown_once_per_file_and_the_already_applied_note_gets_none(tmp_path):
    root = repo(tmp_path)
    commit(root, 40)
    two = INVENTED + "@@ -20,2 +21,3 @@\n made up\n also made up\n+More.\n"
    hint = selfedit.context_hint(two, root)
    assert hint.count("ends at line 40") == 1 and "around line 1:" in hint and "around line 20:" in hint
    done = HEAD + "@@ -40,1 +40,1 @@\n-gone line\n+plan line 40\n"
    hint = selfedit.context_hint(done, root)
    assert "ALREADY APPLIED" in hint and "ends at line" not in hint


def test_a_hunk_with_only_added_lines_gets_the_tail(tmp_path):
    root = repo(tmp_path)
    commit(root, 40)
    hint = selfedit.context_hint(HEAD + "@@ -1,0 +1 @@\n+Probe line.\n", root)
    assert f"{DOC} has 40 lines; around line 1:" in hint and f"... {DOC} ends at line 40 (" in hint
    assert numbered(hint) == list(range(1, 8)) + list(range(33, 41))
