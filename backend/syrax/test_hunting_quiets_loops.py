"""Measured over the 14 days to 2026-10-22: tool_reliability objectives (21, 493 brain calls), repair-capability
objectives (34, 157 calls) and weekly re-research of the same known limitations (34 objectives) changed nothing,
while all the human's briefs used 870 calls. With repro hunts on, a tool's own failure is hunted with a proof, so
the cycle no longer derives tool_reliability or repair objectives, and a limitation researched in the last 90
days is not researched again. With hunts off, nothing changes."""

from syrax import limits
from syrax.autonomy import derive_objectives
from syrax.journal import Journal
from syrax.test_autonomy import make
from syrax.test_limits import FakeSelf, use

KNOWN = [{"kind": "known_limitation", "detail": "no embeddings", "evidence": "docs"},
         {"kind": "known_limitation", "detail": "one task at a time", "evidence": "docs"}]


def test_with_hunts_on_a_failing_tool_is_left_to_the_hunts(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work")
    use(j, t, "str_replace_editor", True, 10)
    use(j, t, "str_replace_editor", False, 10)
    monkeypatch.setenv("SYRAX_REPRO", "1")
    assert limits.choose(j, FakeSelf()) is None
    monkeypatch.setenv("SYRAX_REPRO", "0")
    assert limits.choose(j, FakeSelf())["kind"] == "tool_reliability"


def test_with_hunts_on_a_researched_limitation_is_not_researched_again(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    monkeypatch.setenv("SYRAX_REPRO", "1")
    first = limits.choose(j, FakeSelf(KNOWN))
    j.update_objective_sync(first["objective_id"], status="DONE", note="researched")
    assert limits.researched_subjects(j) == {first["subject"]}
    second = limits.choose(j, FakeSelf(KNOWN), now=None)
    assert second is not None and second["subject"] != first["subject"]


def test_with_hunts_on_a_failing_tool_gets_no_repair_objective(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["desktop", "terminate"])
    t = j.start_task_sync("open notepad")
    use(j, t, "desktop", False, 1, out="Error: the window manager did not answer")
    monkeypatch.setenv("SYRAX_REPRO", "1")
    derive_objectives(j, core.selfmodel)
    assert not [o for o in j.objectives(limit=50) if str(o.get("key") or "").startswith("repair-capability:")]
    monkeypatch.setenv("SYRAX_REPRO", "0")
    derive_objectives(j, core.selfmodel)
    assert [o for o in j.objectives(limit=50) if str(o.get("key") or "").startswith("repair-capability:desktop")]
