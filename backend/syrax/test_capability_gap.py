"""Audit 2026-11-01 (skills S15, the owner's core ask): nothing noticed that the human kept asking for something SYRAX
could not do. Two or more requests that failed or admitted the ability is missing, sharing content words and not
covered by a verified skill, are a capability_gap limitation; its objective closes only on a skill this objective
built, VERIFIED and used successfully once after."""

from syrax import autonomy, limits
from syrax.journal import Journal


def ask(j, goal, answer, refused=False):
    t = j.start_task_sync(goal, kind="conversation")
    if refused:
        j.record_sync("permission.refused", {"tool": "desktop", "reason": "x"}, task_id=t)
    j.record_sync("final", {"text": answer}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS", "result": answer}, task_id=t)
    return t


def test_repeated_requests_it_cannot_do_become_one_gap(tmp_path):
    j = Journal(tmp_path / "j.db")
    ask(j, "convert this epub ebook to pdf", "I can't convert ebooks: no tool for epub files.")
    ask(j, "turn the novel epub ebook into a pdf file", "I cannot do that; I don't have a tool for epub.")
    ask(j, "what is the weather", "Clear, 31 °C.")
    ask(j, "convert epub ebook for me", "I can't", refused=True)  # a refusal is a decision, not a gap
    gaps = limits.capability_gaps(j)
    assert len(gaps) == 1 and gaps[0]["kind"] == "capability_gap"
    assert {"epub", "ebook"} <= set(gaps[0]["check"]["words"]) and len(gaps[0]["evidence"]["tasks"]) == 2


def test_one_miss_or_a_covered_ability_is_not_a_gap(tmp_path):
    j = Journal(tmp_path / "j.db")
    ask(j, "convert this epub ebook to pdf", "I can't convert ebooks.")
    assert limits.capability_gaps(j) == []
    ask(j, "turn the epub ebook into pdf", "I cannot.")
    j.upsert_skill_sync("epub_tools", "convert epub ebook files to pdf", str(tmp_path), "VERIFIED", evidence={})
    assert limits.capability_gaps(j) == []


def test_the_gap_closes_only_on_a_skill_it_built_verified_and_used(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("acquire epub conversion", None, 3, "selfmodel", {"kind": "capability_acquired", "words": ["epub"]})
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] epub", kind="autonomous")
    d = tmp_path / "epub_tools"
    d.mkdir()
    (d / "skill.py").write_text("x")
    j.record_sync("skill.created", {"skill": "epub_tools", "path": str(d)}, task_id=t)
    j.upsert_skill_sync("epub_tools", "convert epub", str(d), "VERIFIED", evidence={}, task_id=t)
    obj = {**j.objective(o["id"]), "last_task_id": t}
    verdict, ev = autonomy.judge(j, obj, j.task(t))
    assert verdict != "DONE" and "real successful call" in ev["missing"]
    j.record_sync("tool.started", {"id": "c", "name": "epub_tools", "args": {}}, task_id=t)
    j.record_sync("tool.completed", {"id": "c", "name": "epub_tools", "ok": True, "output": "converted"}, task_id=t)
    verdict, ev = autonomy.judge(j, obj, j.task(t))
    assert verdict == "DONE" and ev["skill"] == "epub_tools"
