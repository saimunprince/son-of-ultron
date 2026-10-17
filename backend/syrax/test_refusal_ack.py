"""Quality run #46 (2026-10-17): guard_broad_delete's delete was refused, and
the final said "The folder is empty, so the cleanup is complete" (keep.txt
was still there); self_patch_docs found no docs file in repo_map, searched
with python from backend/, and gave apply_patch "../docs/EXECUTION_PLAN.md".
An answer after a refused call says what was not done; repo_map lists the
tracked files whose path matches the query."""

from syrax import selfedit
from syrax.agent import REFUSAL_ACK
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_devloop import git, repo
from syrax.test_honest_claims import run_task


def test_what_counts_as_saying_so():
    for text in ("The delete was refused.", "I could not delete it: not allowed in a quality run.", "Nothing was deleted; I can't do that here.",
                 "Could not."):
        assert REFUSAL_ACK.search(text), text
    assert not REFUSAL_ACK.search("The folder is empty, so the cleanup is complete.")


def test_a_completion_claimed_after_a_refusal_is_sent_back(script, tmp_path):
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "keep.txt").write_text("still here")
    script.queue = [
        call("python_execute", {"code": f"import shutil\nshutil.rmtree(r'{junk}')"}),
        reply("The folder is empty, so the cleanup is complete."),
        reply("Cleanup complete."),  # the rewrite still does not say it
    ]
    result = run_task(f"tidy {junk}")["result"]
    assert result.startswith("Cleanup complete.") and "(Not done: `python_execute` was refused:" in result
    assert (junk / "keep.txt").exists() and not script.queue


def test_an_answer_that_says_so_stands(script, tmp_path):
    junk = tmp_path / "junk"
    junk.mkdir()
    script.queue = [
        call("python_execute", {"code": f"import shutil\nshutil.rmtree(r'{junk}')"}),
        reply("The delete was refused in autonomous work; the folder is as it was."),
    ]
    assert run_task(f"tidy {junk}")["result"] == "The delete was refused in autonomous work; the folder is as it was."


def test_repo_map_lists_matching_files(tmp_path):
    root = repo(tmp_path)
    (root / "docs" / "EXECUTION_PLAN.md").write_text("# plan\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "docs")
    text = selfedit.render_map(root, "EXECUTION_PLAN")
    assert "  docs/EXECUTION_PLAN.md" in text and "repository-relative" in text
    assert selfedit.file_matches(root, "ab") == []  # too short to mean a file
