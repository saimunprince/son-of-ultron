"""Audit 2026-11-01 (skills S8): real use was counted from the skill's LAST verification, so re-verifying unchanged
code wiped its failing record, and a skill_repair objective could close with skill_test plus one easy call and no
fix. The record starts at the current code version's first verification, and a repair needs a new code version."""

from syrax import skillevo
from syrax.autonomy import judge
from syrax.journal import Journal
from syrax.test_skill_deprecation import calls, skill


def test_reverifying_the_same_code_keeps_the_failures(tmp_path):
    j = Journal(tmp_path / "j.db")
    skill(j, tmp_path, "flaky")
    calls(j, "flaky", False, 4)
    calls(j, "flaky", True, 1)
    j.upsert_skill_sync("flaky", "a skill", str(tmp_path / "skills" / "flaky"), "VERIFIED", content_hash=j.skill("flaky").get("content_hash"))
    st = skillevo.real_use(j)["flaky"]
    assert (st["uses"], st["failures"]) == (5, 4)  # the second verification of the same code reset nothing


def test_a_repair_needs_a_new_code_version(tmp_path):
    j = Journal(tmp_path / "j.db")
    skill(j, tmp_path, "flaky")
    j.upsert_skill_sync("flaky", "a skill", str(tmp_path / "skills" / "flaky"), "VERIFIED", content_hash="old-code-hash")
    cv = j.skill("flaky")["code_version"]
    o = j.add_objective_sync("repair flaky", None, 2, "selfmodel", {"kind": "skill_verified", "name": "flaky"},
                             key="limit:skill_repair:flaky:2026-W44")
    j.upsert_skill_sync("flaky", "a skill", str(tmp_path / "skills" / "flaky"), "VERIFIED", content_hash="old-code-hash")  # re-verified, same code
    calls(j, "flaky", True, 1)
    verdict, ev = judge(j, j.objective(o["id"]), None)
    assert verdict == "RETRY" and "new code version" in ev["missing"]
    j.upsert_skill_sync("flaky", "a skill", str(tmp_path / "skills" / "flaky"), "VERIFIED", content_hash="new-code-hash")
    calls(j, "flaky", True, 1)
    verdict, ev = judge(j, j.objective(o["id"]), None)
    assert verdict == "DONE" and j.skill("flaky")["code_version"] > cv
