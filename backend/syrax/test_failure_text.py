"""Live 2026-10-15 (objective 232): apply_patch and the release preflight
showed the last 25 lines of pytest, all deprecation warnings, so SYRAX saw
"AssertionError: asse..." three attempts in a row and guessed the cause. The
failure itself is shown now; and a test that calls monkeypatch.undo() keeps
its own journal (the same attempts wrote half their rows to another one)."""

import os
from pathlib import Path

from syrax import selfedit
from syrax.journal import get_journal
from syrax.test_devloop import repo

OUT = """F                                                                        [100%]
================================== FAILURES ===================================
________________________________ test_expiry __________________________________
syrax\\test_mx.py:9: in test_expiry
    assert "old one" not in block
E   AssertionError: assert 'old one' not in 'LONG-TERM MEMORY: - old one'
---------------------------- Captured stderr setup ----------------------------
UserWarning: Valid config keys have changed in V2
---------------------------- Captured stdout call -----------------------------
facts: 3
============================== warnings summary ===============================
app/tool/base.py:50: PydanticDeprecatedSince20: The `__fields__` attribute is deprecated
""" + "  noise line\n" * 40 + """=========================== short test summary info ===========================
FAILED syrax/test_mx.py::test_expiry - AssertionError: assert 'old one' not in 'LONG-TERM MEMORY: - old one'
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 46 passed, 98 warnings in 47.47s
"""


def test_the_failure_is_shown_not_the_warnings():
    t = selfedit.failure_text(OUT)
    assert "E   AssertionError: assert 'old one' not in" in t and "test_mx.py:9" in t and "facts: 3" in t
    assert "Pydantic" not in t and "noise line" not in t and "Valid config keys" not in t
    assert t.rstrip().endswith("1 failed, 46 passed, 98 warnings in 47.47s")
    assert selfedit.failure_text("boom\n" * 30).count("boom") == 25  # no pytest sections: the last lines
    long = selfedit.failure_text(OUT.replace("facts: 3", "x" * 3000))
    assert len(long) <= 1500 and long.startswith("=") and "1 failed" in long


def test_a_real_failing_run_names_the_assertion(tmp_path):
    root = repo(tmp_path)
    (root / "backend" / "syrax" / "test_mod.py").write_text(
        "import warnings\n\ndef test_v():\n    warnings.warn('old api', DeprecationWarning)\n    assert 1 + 1 == 3\n")
    r = selfedit.run_tests(root, ["backend/syrax/test_mod.py"])
    assert not r["ok"] and "1 failed" in r["summary"]
    assert "assert (1 + 1) == 3" in r["tail"] and "old api" not in r["tail"]


def test_monkeypatch_undo_keeps_the_test_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("SYRAX_PROBE", "1")
    monkeypatch.undo()
    assert os.environ["SYRAX_JOURNAL_FILE"] == str(tmp_path / "journal.db")
    assert Path(get_journal().path) == tmp_path / "journal.db"
