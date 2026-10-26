"""The matrix rows of 2026-10-25 (the queue, backups, the intent ledger, masking, memory
export, deadlines, the boot policy, the skill lifecycle, self-editing by content) name the
tests that exist and render; the folded notes stay on their rows."""

import json
import re
import time
from pathlib import Path

from syrax import backup, probe
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


# ——— the probes' pure parts ———


def test_the_rows_map_their_live_probes():
    caps = {c.id: c for c in cm.CAPABILITIES}
    assert (caps["queue"].live, caps["backups"].live, caps["memory_export"].live) == (["queue"], ["backups"], ["memory_export"])
    assert caps["intent"].live == [] and caps["deadlines"].live == []  # no safe live probe: a real send, a real timeout


def test_a_hello_with_a_queue_list_and_an_answered_queue_pass():
    hello = {"type": "hello", "tools": ["recall"], "running": None, "queue": []}
    answer = {"type": "queue", "items": [{"task_id": "t1", "position": 1, "goal": "later"}]}
    shape = probe.queue_shape(hello, answer)
    assert shape == {"hello_list": True, "answered": True, "items": 1}
    live = cm.live_checks({"ws": {"hello": {"tools": ["recall"]}, "queue": shape}}, None, {"counts": {}, "journal_wal": "wal", "skills_verified": []})
    assert live["queue"] == ("pass", "hello.queue is a list, queue answered with 1 item(s)")
    # an old server: no queue in hello, no answer
    old = probe.queue_shape({"type": "hello", "tools": []}, None)
    assert old == {"hello_list": False, "answered": False, "items": None}
    assert cm.live_checks({"ws": {"queue": old}}, None, {"counts": {}})["queue"][0] == "fail"
    assert cm.live_checks({"ws": {"hello": {"tools": ["x"]}}}, None, {"counts": {}})["queue"] == (None, "")  # not probed: no evidence


def test_memory_export_passes_only_when_the_file_existed(tmp_path):
    ok = {"path": str(tmp_path / "memory-1.json"), "count": 3, "existed": True, "deleted": True}
    r, why = cm.live_checks({"ws": {"memory_export": ok}}, None, {"counts": {}})["memory_export"]
    assert r == "pass" and "3 fact(s)" in why
    gone = {"path": str(tmp_path / "none.json"), "count": 3, "existed": False, "deleted": False}
    assert cm.live_checks({"ws": {"memory_export": gone}}, None, {"counts": {}})["memory_export"][0] == "fail"
    assert cm.live_checks({"ws": {"memory_export": {"error": "no memory_exported within 30 s"}}}, None, {"counts": {}})["memory_export"] == \
        ("fail", "no memory_exported within 30 s")
    assert cm.live_checks({"ws": {}}, None, {"counts": {}})["memory_export"] == (None, "")


def seeded_backup(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    j = Journal(cfg / "journal.db")
    t = j.start_task_sync("task")
    j.record_sync("final", {"content": "done"}, task_id=t)
    (cfg / "brains.json").write_text(json.dumps({"keys": {"groq": "gsk_x"}}), encoding="utf-8")
    m = backup.snapshot(j, now=time.time() - 3600)  # an hour old
    j.close()
    return cfg / "backups", Path(m["dir"])


def test_a_seeded_snapshot_verifies_and_is_fresh_and_a_stale_or_broken_one_fails(tmp_path):
    root, d = seeded_backup(tmp_path)
    now = time.time()
    bk = probe.backups_check(root, now)
    assert bk["ok"] and bk["fresh"] and bk["problems"] == [] and bk["dir"] == str(d) and bk["snapshots"] == 1 and 0.9 <= bk["age_h"] <= 1.1
    journal = {"counts": {}, "journal_wal": "wal", "skills_verified": []}
    r, why = cm.live_checks({"backups": bk}, None, journal)["backups"]
    assert r == "pass" and d.name in why and "verifies" in why
    # three days later the daily snapshot has not happened: stale, said with the age
    stale = probe.backups_check(root, now + 3 * 86400)
    assert stale["ok"] and not stale["fresh"]
    r, why = cm.live_checks({"backups": stale}, None, journal)["backups"]
    assert r == "fail" and "older than the daily snapshot allows" in why
    # a flipped byte in the copied brains.json: the manifest catches it
    p = d / "brains.json"
    p.write_bytes(p.read_bytes()[:-1] + b"X")
    broken = probe.backups_check(root, now)
    assert not broken["ok"] and any("brains.json" in x for x in broken["problems"])
    r, why = cm.live_checks({"backups": broken}, None, journal)["backups"]
    assert r == "fail" and "brains.json" in why


def test_no_snapshot_folder_is_no_evidence_not_a_pass(tmp_path):
    assert probe.backups_check(tmp_path / "none") == {}
    journal = {"counts": {}, "journal_wal": "wal", "skills_verified": []}
    assert cm.live_checks({"backups": {}}, None, journal)["backups"] == (None, "no snapshot folder")
    assert cm.live_checks({}, None, journal)["backups"] == (None, "")
    assert cm.live_checks({"backups": {"error": "boom"}}, None, journal)["backups"] == ("fail", "backups: boom")
    # the rows: a seeded, fresh snapshot plus a passing test turns the backups row GREEN; without a probe it is UNVERIFIED
    root, _ = seeded_backup(tmp_path)
    cap = next(c for c in cm.CAPABILITIES if c.id == "backups")
    tests = {"syrax.test_backup::test_snapshot_copies_a_consistent_journal_and_the_manifest_tells_the_truth": "pass"}
    live = cm.live_checks({"backups": probe.backups_check(root)}, None, journal)
    assert cm.evaluate(cap, {"counts": {}, "tool_stats": {}}, tests, live)["status"] == cm.GREEN
    assert cm.evaluate(cap, {"counts": {}, "tool_stats": {}}, tests, cm.live_checks({}, None, journal))["status"] == cm.UNVERIFIED
