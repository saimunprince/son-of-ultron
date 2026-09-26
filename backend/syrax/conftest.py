"""Test isolation for the SYRAX layer.

Every test gets its own journal file and a fresh core, so no test can touch
backend/config/journal.db or inherit a running task from another test.
"""

import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp()
os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")
os.environ.setdefault("SYRAX_DISABLE_WHISPER_WARMUP", "1")
os.environ.setdefault("SYRAX_BROWSER", "0")
os.environ.setdefault("SYRAX_MEMORY_FILE", os.path.join(_tmp, "memory.json"))
os.environ.setdefault("SYRAX_HISTORY_FILE", os.path.join(_tmp, "history.jsonl"))
os.environ.setdefault("SYRAX_BRAINS_FILE", os.path.join(_tmp, "brains.json"))
os.environ.setdefault("SYRAX_JOURNAL_FILE", os.path.join(_tmp, "journal.db"))


@pytest.fixture(autouse=True)
def fresh_journal_and_core(tmp_path, monkeypatch):
    import syrax.journal as journal_mod

    monkeypatch.setenv("SYRAX_JOURNAL_FILE", str(tmp_path / "journal.db"))
    monkeypatch.setattr(journal_mod, "_journal", None)
    try:
        import syrax.skills as skills_mod

        monkeypatch.setattr(skills_mod, "SKILLS_ROOT", tmp_path / "skills")  # never write into backend/skills
    except Exception:
        pass
    try:
        import syrax.core as core_mod
    except Exception:  # core imports the agent stack; journal-only tests don't need it
        core_mod = None
    if core_mod is not None:
        monkeypatch.setattr(core_mod, "_core", None)
    yield
    j = journal_mod._journal
    if j is not None:
        j.close()
