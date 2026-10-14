"""Phase 5 of the self-improvement plan: the archive of SYRAX's own variants.
A release attempt becomes a row (parent → head, decision); a quality run at
that head scores it; parent selection favours score and penalises children;
the brief carries it for a release objective; the ledger renders it."""

import asyncio
import time

from syrax import archive, autonomy
from syrax.devloop import JUDGES
from syrax.journal import Journal


def seed(j):
    a = j.add_archive_sync("aaaaaaa1", "0000000", "COMMITTED", "first change", 1, "t1", 1)
    b = j.add_archive_sync("bbbbbbb2", "aaaaaaa1", "COMMITTED", "second change", 2, "t2", 2)
    j.add_archive_sync(None, "bbbbbbb2", "ROLLED_BACK", "a failed try", 3, "t3", 3)
    c = j.add_archive_sync("ccccccc3", "aaaaaaa1", "COMMITTED", "a sibling", 3, "t4", 4)
    return a, b, c


def test_rows_score_and_weights(tmp_path):
    j = Journal(tmp_path / "j.db")
    seed(j)
    assert j.score_archive_sync("bbbbbbb2", 90.0, 7) == 1
    assert j.score_archive_sync("ccccccc3abcdef", 40.0, 8) == 1  # a full sha scores the short head it starts with
    assert j.score_archive_sync("", 1.0, None) == 0
    rows = {v["head"]: v for v in archive.variants(j) if v["head"]}
    assert rows["aaaaaaa1"]["children"] == 2 and rows["bbbbbbb2"]["children"] == 1 and rows["ccccccc3"]["children"] == 0
    assert rows["aaaaaaa1"]["weight"] == 0.0  # unscored
    assert rows["bbbbbbb2"]["weight"] > rows["ccccccc3"]["weight"] > 0
    assert archive.weight(90.0, 0) > archive.weight(90.0, 3) and archive.weight(None, 0) == 0.0


def test_parent_selection_and_lineage(tmp_path):
    j = Journal(tmp_path / "j.db")
    assert archive.select_parent(j) is None
    a, b, c = seed(j)
    newest = archive.select_parent(j)
    assert newest["head"] == "ccccccc3" and "no quality run" in newest["why"]
    j.score_archive_sync("bbbbbbb2", 90.0, 7)
    j.score_archive_sync("ccccccc3", 95.0, 8)
    best = archive.select_parent(j)
    assert best["head"] == "ccccccc3" and "weight" in best["why"]  # higher score, no children
    for _ in range(3):
        j.add_archive_sync(f"d{_}ddddd", "ccccccc3", "COMMITTED", "child", None, None, None)
    assert archive.select_parent(j)["head"] == "bbbbbbb2"  # three children: the sibling wins now
    chain = archive.lineage(j, "bbbbbbb2")
    assert [v["head"] for v in chain] == ["bbbbbbb2", "aaaaaaa1"]
    assert [d["summary"] for d in archive.dead_ends(j, 3)] == ["a failed try"]


def test_a_release_attempt_is_archived_from_its_report(tmp_path):
    j = Journal(tmp_path / "j.db")
    row = archive.record_attempt(j, {"outcome": "COMMITTED", "head": "abc1234", "commit": "def5678"}, "fix the editor", 5, "t9", 11)
    assert row["head"] == "def5678" and row["parent"] == "abc1234" and row["objective_id"] == 5 and row["experiment_id"] == 11
    dead = archive.record_attempt(j, {"outcome": "ROLLED_BACK", "head": "abc1234"}, "try again", 5, "t10", 12)
    assert dead["head"] is None and dead["decision"] == "ROLLED_BACK"
    assert archive.record_attempt(j, {"outcome": "SKIPPED", "head": "abc1234"}, "x", None, None, None) is None


def test_the_brief_names_the_running_build_the_best_parent_and_the_dead_ends(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    assert archive.brief(j, "abc1234") == ""
    seed(j)
    j.score_archive_sync("bbbbbbb2", 90.0, 7)
    text = archive.brief(j, "bbbbbbb2", objective_id=3)
    assert "running build bbbbbbb" in text and "score 90%" in text and "best parent to build on: bbbbbbb" in text
    assert "dead end for this objective: ROLLED_BACK from bbbbbbb" in text and "3 committed variant(s), 1 attempt(s)" in text
    monkeypatch.setattr(archive, "brief", lambda journal, head, objective_id=None, budget=700: f"ARCHIVE for {objective_id}\n")
    assert autonomy.archive_brief(j, {"id": 3, "check_spec": {"kind": "change_released"}}) == "ARCHIVE for 3\n"
    assert autonomy.archive_brief(j, {"id": 3, "check_spec": {"kind": "task_success"}}) == ""


def test_render_and_the_judge(tmp_path):
    j = Journal(tmp_path / "j.db")
    empty = archive.render(j, "abc1234", generated="2026-10-14 13:00")
    assert empty.startswith("# SYRAX archive") and "no release attempt recorded yet" in empty
    seed(j)
    j.score_archive_sync("bbbbbbb2", 90.0, 7)
    text = archive.render(j, "bbbbbbb2", generated="2026-10-14 13:00")
    assert "Variants committed: 3; attempts that did not land: 1; scored: 1." in text
    assert "Lineage of the running build: `bbbbbbb` 90% ← `aaaaaaa`" in text
    assert "| COMMITTED | `aaaaaaa` → `bbbbbbb` | 90% | 1 |" in text and "| ROLLED_BACK | `bbbbbbb` → `-` | - |" in text
    assert "backend/syrax/archive.py" in JUDGES
