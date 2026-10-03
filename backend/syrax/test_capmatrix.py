"""The capability matrix is computed from evidence; these pin the rules."""

import re
import time
from pathlib import Path

from syrax import capmatrix as cm
from syrax.journal import Journal

JUNIT = """<testsuites><testsuite name="pytest" tests="4" failures="1" errors="0" skipped="1" time="3.5">
<testcase classname="syrax.test_editor" name="test_a"/>
<testcase classname="syrax.test_editor" name="test_b"><failure message="x"/></testcase>
<testcase classname="syrax.test_desktop" name="test_c"/>
<testcase classname="syrax.test_voice" name="test_d"><skipped/></testcase>
</testsuite></testsuites>"""


def seeded(tmp_path, now):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work")
    for i in range(4):
        j.record_sync("tool.started", {"id": f"e{i}", "name": "str_replace_editor", "args": {"command": "view", "path": "x"}}, task_id=t)
        j.record_sync("tool.completed", {"id": f"e{i}", "name": "str_replace_editor", "ok": True, "output": "ok"}, task_id=t)
    j.record_sync("tool.started", {"id": "d0", "name": "desktop", "args": {"action": "open"}}, task_id=t)
    j.record_sync("tool.failed", {"id": "d0", "name": "desktop", "ok": False, "output": "Error"}, task_id=t)
    j.record_sync("tool.started", {"id": "d1", "name": "desktop", "args": {"action": "system_info"}}, task_id=t)
    j.record_sync("tool.completed", {"id": "d1", "name": "desktop", "ok": True, "output": "16 cores"}, task_id=t)
    j.record_sync("final", {"text": "done"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    j.add_quality_run_sync([{"id": "file_edit", "ok": True}, {"id": "desktop_cpu", "ok": False}, {"id": "python", "ok": True}], 66.7, "PASS", brain="x")
    j.close()
    return tmp_path / "j.db"


def cap(**kw):
    base = dict(id="x", label="X", implementation=cm.CURRENT, where="here")
    base.update(kw)
    return cm.Capability(**base)


def test_rules_in_order(tmp_path):
    now = time.time()
    db = seeded(tmp_path, now)
    junit = tmp_path / "j.xml"
    junit.write_text(JUNIT)
    journal = cm.read_journal(db, now)
    tests = cm.read_junit(junit)
    live = cm.live_checks(None, None, journal)
    ev = lambda c: cm.evaluate(c, journal, tests, live, now)["status"]
    assert ev(cap(implementation=cm.MISSING)) == cm.RED
    assert ev(cap(implementation=cm.PLANNED)) == cm.UNVERIFIED
    assert ev(cap(tools=["str_replace_editor"], tests=["syrax.test_editor::test_a"])) == cm.GREEN
    assert ev(cap(tools=["str_replace_editor"], tests=["syrax.test_editor::*"])) == cm.RED  # test_b fails
    assert ev(cap(tools=["desktop"], tests=["syrax.test_desktop::*"], quality_cases=["desktop_cpu"])) == cm.RED  # case failed
    assert ev(cap(tools=["desktop"], tests=["syrax.test_desktop::*"])) == cm.YELLOW  # 50 % failure share
    assert ev(cap(tools=["python_execute"], tests=["syrax.test_desktop::*"])) == cm.UNVERIFIED  # tests pass, never ran
    assert ev(cap(tools=["python_execute"], tests=["syrax.test_desktop::*"], quality_cases=["python"])) == cm.GREEN  # quality pass is runtime evidence
    assert ev(cap(tests=["syrax.test_voice::*"])) == cm.UNVERIFIED  # only a skipped test
    assert ev(cap(tools=["str_replace_editor"], tests=["syrax.test_editor::test_a"], needs_human=True)) == cm.UNVERIFIED
    assert ev(cap(tools=["str_replace_editor"], tests=["syrax.test_editor::test_a"], implementation=cm.PARTIAL)) == cm.YELLOW
    assert ev(cap(tests=["syrax.test_editor::test_a"], live=["journal_wal"])) == cm.GREEN  # live pass is runtime evidence


def test_old_evidence_and_live_outcomes(tmp_path):
    now = time.time()
    db = seeded(tmp_path, now)
    journal = cm.read_journal(db, now + 10 * 86400)  # ten days later: evidence outside the window
    tests = {"syrax.test_editor::test_a": "pass"}
    live = cm.live_checks({"http": {"health": {"json": {"status": "online"}}}, "voice": {"tts": {"error": "HTTP Error 502"}},
                           "ui": {"status": 500}}, {"status": "GREEN", "gates": {"tsc": "PASS", "eslint": "PASS", "node_test": "PASS", "next_build": "PASS", "pytest": "PASS"}}, journal)
    ev = lambda c: cm.evaluate(c, journal, tests, live, now + 10 * 86400)["status"]
    assert ev(cap(tools=["str_replace_editor"], tests=["syrax.test_editor::test_a"])) == cm.UNVERIFIED  # stale runtime evidence
    assert ev(cap(tests=["syrax.test_editor::test_a"], live=["health"])) == cm.GREEN
    assert ev(cap(tests=["syrax.test_editor::test_a"], live=["tts"])) == cm.BLOCKED
    assert ev(cap(tests=["syrax.test_editor::test_a"], live=["ui"])) == cm.RED
    assert ev(cap(tests=["syrax.test_editor::test_a"], live=["gate_frontend"])) == cm.GREEN


def test_tool_stats_match_the_journals_own(tmp_path):
    import sqlite3
    now = time.time()
    db = seeded(tmp_path, now)
    j = Journal(db)
    theirs = j.tool_stats()
    j.close()
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    mine = cm.tool_stats(c, now)
    for name, st in theirs.items():
        assert {k: mine[name][k] for k in ("uses", "successes", "failures", "last_outcome")} == {k: st[k] for k in ("uses", "successes", "failures", "last_outcome")}


def test_every_spec_test_pattern_matches_a_real_test():
    names = set()
    for f in Path(__file__).parent.glob("test_*.py"):
        for m in re.finditer(r"^def (test_\w+)", f.read_text(encoding="utf-8"), re.M):
            names.add(f"syrax.{f.stem}::{m.group(1)}")
    for c in cm.CAPABILITIES:
        for p in c.tests:
            assert any(cm.fnmatch.fnmatch(n, p) for n in names), f"{c.id}: pattern {p} matches no test"


def test_contract_capabilities_are_all_present_and_rendered(tmp_path):
    required = ["Startup", "LLM provider routing", "Agent execution", "Filesystem access", "Shell / code execution", "Browser automation", "Screenshot",
                "Desktop automation", "Memory", "Durable journal", "Task persistence", "Task cancellation", "Recovery", "Frontend", "WebSocket", "Voice input",
                "Voice output", "Verification / release gate", "Self-model", "Self-improvement", "Skill / tool creation"]
    labels = [c.label for c in cm.CAPABILITIES]
    for r in required:
        assert any(l.startswith(r) for l in labels), r
    db = seeded(tmp_path, time.time())
    rows, text = cm.build(db, head="abc1234")
    assert text.startswith("# SYRAX capability matrix") and "| Capability | Implementation | Runtime Test | Verification | Evidence | Status |" in text
    assert "## Totals" in text and f"total {len(cm.CAPABILITIES)}" in text and "## System map coverage" in text
    assert all(r["status"] in cm.ORDER for r in rows)


def test_architecture_doc_names_every_system_map_component():
    doc = (cm.REPO_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    for name in cm.map_coverage()["components"]:
        assert name in doc, f"docs/ARCHITECTURE.md does not mention component {name!r}"
