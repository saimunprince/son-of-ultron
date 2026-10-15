"""Live 2026-10-15 (objective 232, attempt 2): SYRAX released while its own new
test failed; the full gate took eight minutes to say so and the rollback took
the edits away. In SYRAX's own work the tests that cover the change run first:
when they fail, the release is refused with their output and the edits stay
for a fix forward; when they pass, the gate runs as before."""

import asyncio

import pytest

from syrax.devloop import DevLoop
from syrax.journal import Journal
from syrax.test_devloop import PASS, repo

PLAN = {"why": "objective", "risk": "mod callers", "tests": "test_mod.py"}


def own(tmp_path, root):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] change mod", kind="autonomous")
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    dl.begin_task()
    return j, dl


def test_failing_covering_tests_refuse_the_release_and_keep_the_edits(tmp_path):
    root = repo(tmp_path)
    j, dl = own(tmp_path, root)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 2\n")
    (root / "backend" / "syrax" / "test_mod.py").write_text("import sys; sys.path.insert(0, '.')\nfrom syrax.mod import VALUE\n\ndef test_v():\n    assert VALUE == 3\n")
    with pytest.raises(ValueError, match="the tests that cover your change fail") as e:
        asyncio.run(dl.release("bump VALUE", PLAN))
    assert "1 failed" in str(e.value) and "syrax/test_mod.py" in str(e.value)
    assert (root / "backend" / "syrax" / "mod.py").read_text() == "VALUE = 2\n"  # kept for a fix forward
    assert not [x for x in j.verifications(limit=5)]  # the full gate never ran


def test_passing_covering_tests_go_on_to_the_gate(tmp_path):
    root = repo(tmp_path)
    j, dl = own(tmp_path, root)
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 2\n")
    (root / "backend" / "syrax" / "test_mod.py").write_text("import sys; sys.path.insert(0, '.')\nfrom syrax.mod import VALUE\n\ndef test_v():\n    assert VALUE == 2\n")
    assert asyncio.run(dl.release("bump VALUE", PLAN))["outcome"] == "COMMITTED"
