"""The matrix rows of 2026-10-25 (the queue, backups, the intent ledger, masking, memory
export, deadlines, the boot policy, the skill lifecycle, self-editing by content) name the
tests that exist and render; the folded notes stay on their rows."""

import re
import time
from pathlib import Path

from syrax import capmatrix as cm
from syrax.journal import Journal

NEW = {"queue": "Task queue", "backups": "Backups with verified restore", "intent": "Intent ledger",
       "masking": "Credential masking", "memory_export": "Memory inspection, export and correction",
       "deadlines": "Task deadlines and tool timeouts", "boot_policy": "Boot policy for interrupted tasks",
       "skill_lifecycle": "Skill lifecycle", "selfedit": "Self-editing tools"}


def collected():
    names = set()
    for f in Path(__file__).parent.glob("test_*.py"):
        for m in re.finditer(r"^def (test_\w+)", f.read_text(encoding="utf-8"), re.M):
            names.add(f"syrax.{f.stem}::{m.group(1)}")
    return names


def test_every_new_row_is_current_and_maps_tests_that_exist():
    caps = {c.id: c for c in cm.CAPABILITIES}
    names = collected()
    for cid, label in NEW.items():
        cap = caps[cid]
        assert cap.label.startswith(label) and cap.implementation == cm.CURRENT, cid
        assert cap.tests, cid
        for p in cap.tests:
            assert any(cm.fnmatch.fnmatch(n, p) for n in names), f"{cid}: pattern {p} matches no test"


def test_the_folded_notes_and_tests_sit_on_the_existing_rows():
    caps = {c.id: c for c in cm.CAPABILITIES}
    assert "syrax.test_review_unavailable::*" in caps["release"].tests and "REVIEW_UNAVAILABLE" in caps["release"].note
    assert "APPLIED BY CONTENT" in caps["selfedit"].note and caps["selfedit"].tools == ["apply_patch", "repo_map"]
    assert caps["permissions"].tests == ["syrax.test_permissions*::*"] and "test_guard_weakening" in caps["permissions"].note  # the tests list is a contract
    assert "syrax.test_memory_truth::*" in caps["memory"].tests and "syrax.test_learn_supports_claim::*" in caps["knowledge"].tests
    assert "hud/*.test.js" in caps["presence"].note


def test_the_new_rows_render_in_the_matrix(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.close()
    rows, text = cm.build(tmp_path / "j.db", head="abc1234", now=time.time())
    by_id = {r["id"]: r for r in rows}
    for cid, label in NEW.items():
        assert by_id[cid]["label"].startswith(label) and f"| {by_id[cid]['label']} |" in text
        assert by_id[cid]["status"] in cm.ORDER
