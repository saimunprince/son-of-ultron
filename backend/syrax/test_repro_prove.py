"""Brief Factory (2026-10-22): repro.prove runs a test on a throwaway worktree of the base commit and judges it by
pytest's own report, never by a model's words. A test that sees the bug is RED; with the fix it must pass, and so
must the tests that import the changed module. This is what the human did by hand for the 13 briefs SYRAX landed
on the first attempt (2026-10-17..19)."""

from syrax import repro
from syrax.test_devloop import git

REPRO = "from syrax.calc import add\n\n\ndef test_adds():\n    assert add(2, 3) == 5\n"
FIX = "--- a/backend/syrax/calc.py\n+++ b/backend/syrax/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
TEST = "backend/syrax/test_calc_repro.py"


def shaped_repo(tmp_path):
    """A repository shaped like SYRAX's: backend/syrax with a bug, an old test, the secret-free example config."""
    root = tmp_path / "live"
    (root / "backend" / "syrax").mkdir(parents=True)
    (root / "backend" / "config").mkdir()
    git(root, "init", "-q")
    (root / ".gitignore").write_text(".syrax/\nbackend/config/config.toml\n")
    (root / "backend" / "config" / "config.syrax.example.toml").write_text("[llm]\n")
    (root / "backend" / "syrax" / "calc.py").write_bytes(b"def add(a, b):\n    return a - b\n")
    (root / "backend" / "syrax" / "test_calc_old.py").write_bytes(b"from syrax.calc import add\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


def test_a_test_that_sees_the_bug_is_red_and_the_fix_proves_it(tmp_path):
    root = shaped_repo(tmp_path)
    proof = repro.prove(root, TEST, REPRO, fix_diff=FIX)
    assert proof["verdict"] == "PROVEN", proof
    assert proof["red"]["failed"] and proof["red"]["failed"][0].endswith("::test_adds")
    assert proof["green"]["ran"] == [TEST, "backend/syrax/test_calc_old.py"]  # the tests that import calc ran too
    assert proof["sha256"] == repro.test_sha(REPRO) and proof["base"] == git(root, "rev-parse", "HEAD")
    assert git(root, "worktree", "list").count("\n") == 0  # the throwaway worktree is gone
    assert git(root, "status", "--porcelain") == ""  # and the tree it came from is untouched


def test_what_does_not_prove_the_bug_gets_its_own_verdict(tmp_path):
    root = shaped_repo(tmp_path)

    def verdict(test=REPRO, fix=None):
        return repro.prove(root, TEST, test, fix_diff=fix, red_runs=1)

    assert verdict("from syrax.calc import add\n\n\ndef test_one():\n    assert add(1, 0) == 1\n")["verdict"] == "NOT_RED"
    assert verdict("from syrax.calc import sub\n\n\ndef test_sub():\n    assert sub(3, 2) == 1\n")["verdict"] == "RED_ERROR"
    assert verdict(fix=FIX.replace("a + b", "a * b"))["verdict"] == "NOT_FIXED"
    contract = verdict(fix=FIX.replace("+    return a + b", "+    return a + b if (a or b) else 1"))
    assert contract["verdict"] == "CONTRACT" and "test_calc_old" in contract["reason"]
    assert verdict(fix=FIX.replace("-    return a - b", "-    return a / b"))["verdict"] == "FIX_DOES_NOT_APPLY"
    touches_test = FIX + f"--- /dev/null\n+++ b/{TEST}\n@@ -0,0 +1 @@\n+x = 1\n"
    assert verdict(fix=touches_test)["verdict"] == "INVALID"
