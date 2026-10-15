"""Live 2026-10-15 (objective 266, attempt 2): a three-file diff whose
selfmodel.py hunk did not match was answered "corrupt patch at <stdin>:56"
with brains.py's context, three times, and the attempt ended "Brain latency
metrics successfully added ..." with nothing applied. The refusal names the
file that does not match and shows that file; the claim is sent back."""

from syrax import selfedit
from syrax.agent import OWN_WORK_CLAIM
from syrax.test_devloop import git, repo

THREE = (
    "diff --git a/backend/syrax/mod.py b/backend/syrax/mod.py\n"
    "--- a/backend/syrax/mod.py\n"
    "+++ b/backend/syrax/mod.py\n"
    "@@ -1 +1 @@\n"
    "-VALUE = 1\n"
    "+VALUE = 2\n"
    "diff --git a/backend/syrax/two.py b/backend/syrax/two.py\n"
    "--- a/backend/syrax/two.py\n"
    "+++ b/backend/syrax/two.py\n"
    "@@ -1,4 +1,5 @@\n"  # miscounted, and its context is not what two.py holds
    " def f():\n"
    "-    return 'old text that is not there'\n"
    "+    return 'new'\n"
    "+\n"
    "diff --git a/backend/syrax/test_three.py b/backend/syrax/test_three.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/backend/syrax/test_three.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+def test_x():\n"
    "+    assert True\n"
)


def test_the_refusal_names_the_file_that_does_not_match(tmp_path):
    root = repo(tmp_path)
    (root / "backend" / "syrax" / "two.py").write_text("def f():\n    return 'what it really says'\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "two")
    try:
        selfedit.apply_patch(THREE, root, run=False)
    except ValueError as e:
        msg = str(e)
    else:
        raise AssertionError("the patch should not apply")
    assert "backend/syrax/two.py" in msg and "corrupt patch" not in msg
    assert "what it really says" in msg  # the hint shows two.py, the file that does not match
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"  # nothing applied


def test_a_successful_addition_claimed_by_own_work_is_caught():
    assert OWN_WORK_CLAIM.search("Brain latency metrics successfully added to BrainRouter and SelfModel.")
    assert OWN_WORK_CLAIM.search("The probe was successfully integrated.")
    assert not OWN_WORK_CLAIM.search("Nothing was changed: the patch did not apply to selfmodel.py.")
