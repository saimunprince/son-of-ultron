"""Live 2026-10-15 (objective 266, attempt 1): a git-style diff (diff --git,
new file mode) with a miscounted hunk went to the file-by-file plan; the split
left the new file's header lines at the end of the section before, so that
section created the new file empty and the new file's own section failed with
"already exists", after the first two files had been changed. Sections keep
their git headers, and a failed apply changes nothing."""

from syrax import selfedit
from syrax.test_devloop import repo

GITDIFF = (
    "diff --git a/backend/syrax/mod.py b/backend/syrax/mod.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/backend/syrax/mod.py\n"
    "+++ b/backend/syrax/mod.py\n"
    "@@ -1,3 +1,3 @@\n"  # miscounted: the file has one line, so the diff goes file by file with --recount
    "-VALUE = 1\n"
    "+VALUE = 2\n"
    "diff --git a/backend/syrax/test_new_ms.py b/backend/syrax/test_new_ms.py\n"
    "new file mode 100644\n"
    "index 0000000..3333333\n"
    "--- /dev/null\n"
    "+++ b/backend/syrax/test_new_ms.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+def test_x():\n"
    "+    assert True\n"
)


def test_git_headers_stay_with_their_file():
    parts = selfedit.file_sections(GITDIFF)
    assert len(parts) == 2
    assert parts[0].startswith("diff --git a/backend/syrax/mod.py") and "test_new_ms" not in parts[0]
    assert parts[1].startswith("diff --git a/backend/syrax/test_new_ms.py") and "new file mode 100644" in parts[1]


def test_a_git_style_two_file_patch_with_a_miscounted_hunk_applies(tmp_path):
    root = repo(tmp_path)
    rep = selfedit.apply_patch(GITDIFF, root, run=False)
    assert sorted(rep["files"]) == ["backend/syrax/mod.py", "backend/syrax/test_new_ms.py"]
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 2\n"
    assert (root / "backend" / "syrax" / "test_new_ms.py").read_text() == "def test_x():\n    assert True\n"


def test_a_failed_apply_puts_every_file_back(tmp_path, monkeypatch):
    root = repo(tmp_path)
    real = selfedit._git
    applies = []

    def flaky(args, cwd, stdin=None, **kw):
        if args[:1] == ["apply"] and "--check" not in args:
            applies.append(1)
            if len(applies) == 2:  # the second section fails after the first one applied
                class R:
                    returncode, stdout, stderr = 1, "", "error: disk full"
                return R()
        return real(args, cwd, stdin=stdin, **kw)

    monkeypatch.setattr(selfedit, "_git", flaky)
    try:
        selfedit.apply_patch(GITDIFF, root, run=False)
    except RuntimeError as e:
        assert "nothing was changed" in str(e)
    else:
        raise AssertionError("the apply should have failed")
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 1\n"
    assert not (root / "backend" / "syrax" / "test_new_ms.py").exists()
