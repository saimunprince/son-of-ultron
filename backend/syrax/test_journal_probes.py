"""Capability matrix rows of 2026-10-25 that had no runtime evidence read it from the journal (2026-10-26; the
ledger of that day: UNVERIFIED 9). Masking: the newest journaled events hold no credential redact.CREDENTIAL would
have masked (live: 0 of 2000). The boot policy: the dismissals it journaled (core._settle_decision's notes, not a
human's "dismissed by human"). The skill lifecycle: every VERIFIED skill carries a content hash. No evidence is no
pass: an empty window stays UNVERIFIED. The intent ledger and deadlines keep no probe (test_capmatrix_rows)."""

import time

from syrax import capmatrix as cm
from syrax.core import _settle_decision
from syrax.journal import Journal

KEY = "gsk_" + "A1b2C3d4E5f6G7h8I9j0K1l2"  # the shape redact.CREDENTIAL masks (a Groq key), not a real one


def journal_with(tmp_path, events=(), skills=()):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work")
    for type_, payload in events:
        # a task ends once: every dismissal is its own task, as at a real boot
        j.record_sync(type_, payload, task_id=j.start_task_sync("interrupted") if type_ == "task.cancelled" else t)
    for name, h in skills:
        j.upsert_skill_sync(name, "a skill", str(tmp_path / name), "VERIFIED", content_hash=h)
    j.close()
    return cm.read_journal(tmp_path / "j.db", time.time())


def live(journal):
    return cm.live_checks({}, None, journal)


def test_the_rows_name_their_probes():
    caps = {c.id: c for c in cm.CAPABILITIES}
    assert caps["masking"].live == ["masked_record"]
    assert caps["boot_policy"].live == ["boot_decisions"]
    assert caps["skill_lifecycle"].live == ["skill_hashes"]


def test_a_clean_record_is_the_masking_s_evidence(tmp_path):
    j = journal_with(tmp_path, [("think", {"step": 1, "content": "the key is [credential masked]"})])
    assert j["masked_record"]["raw"] == 0 and j["masked_record"]["scanned"] >= 2
    result, why = live(j)["masked_record"]
    assert result == "pass" and why.startswith("0 raw credentials in the newest")


def test_a_raw_credential_in_the_record_fails_the_row(tmp_path):
    j = journal_with(tmp_path, [("think", {"step": 1, "content": f"use {KEY}"})])
    result, why = live(j)["masked_record"]
    assert result == "fail" and why.startswith("1 of the newest") and KEY not in why


def test_the_boot_policy_s_own_dismissals_are_its_evidence(tmp_path):
    now = time.time()
    notes = [_settle_decision({"kind": "eval", "recovery_state": "RESUMABLE", "updated": now}, now)[0],
             _settle_decision({"kind": "autonomous", "recovery_state": "RESUMABLE", "updated": now}, now)[0]]
    events = [("task.cancelled", {"error": n}) for n in notes]
    events.append(("task.cancelled", {"error": "dismissed by human: quality case cut by a manual restart on 2026-10-22"}))
    events.append(("task.cancelled", {"error": "removed from the queue: removed by human"}))
    j = journal_with(tmp_path, events)
    assert j["counts"]["boot_decisions"] == 2
    assert live(j)["boot_decisions"] == ("pass", f"2 interrupted task(s) settled by the boot policy in {cm.WINDOW_DAYS} d")


def test_nothing_interrupted_is_no_evidence(tmp_path):
    j = journal_with(tmp_path)
    assert live(j)["boot_decisions"] == (None, f"0 boot decisions in {cm.WINDOW_DAYS} d (nothing was interrupted)")


def test_every_verified_skill_with_a_hash_is_the_lifecycle_s_evidence(tmp_path):
    j = journal_with(tmp_path, skills=[("a", "1" * 64), ("b", "2" * 64)])
    assert live(j)["skill_hashes"] == ("pass", "2 of 2 VERIFIED skills carry a content hash")


def test_a_verified_skill_without_a_hash_fails_the_row(tmp_path):
    j = journal_with(tmp_path, skills=[("a", "1" * 64), ("b", None)])
    result, why = live(j)["skill_hashes"]
    assert result == "fail" and why.startswith("1 of 2 VERIFIED skills carry no content hash")


def test_no_verified_skill_is_no_evidence(tmp_path):
    assert live(journal_with(tmp_path))["skill_hashes"] == (None, "no VERIFIED skill")


def test_the_rows_turn_green_only_on_evidence(tmp_path):
    caps = {c.id: c for c in cm.CAPABILITIES}
    passing = {"masking": {"syrax.test_redact::test_x": "pass"}, "skill_lifecycle": {"syrax.test_skill_lifecycle::test_x": "pass"},
               "boot_policy": {"syrax.test_boot_policy::test_x": "pass"}}
    clean = journal_with(tmp_path, skills=[("a", "1" * 64)])
    for key in ("masking", "skill_lifecycle"):
        assert cm.evaluate(caps[key], clean, passing[key], live(clean))["status"] == cm.GREEN, key
    assert cm.evaluate(caps["boot_policy"], clean, passing["boot_policy"], live(clean))["status"] == cm.UNVERIFIED
