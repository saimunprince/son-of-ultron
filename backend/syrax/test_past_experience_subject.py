"""past_experience recalls objectives about the same subject, not the same check kind with templated words, and puts
failures first (live 2026-10-27: 801 of 1,100 recalled entries were DONE objectives with nothing in common but kind)."""
from syrax.autonomy import EXPERIENCE_COMMON_MIN_POOL, goal_words, past_experience
from syrax.journal import Journal


def _limitation(j, key, detail, status=None, lesson="x"):
    plan = [f"`research` how comparable systems overcome: {detail}.", "`learn` one verified conclusion with sources.",
            "Say what change to SYRAX it suggests and what it would cost; build nothing yet."]
    o = j.add_objective_sync(
        goal=f"My biggest measured limitation right now: {detail}. Improve it. Plan: " + " ".join(f"({i + 1}) {s}" for i, s in enumerate(plan)),
        source="selfmodel", key=key, check={"kind": "knowledge_stored", "topic": detail[:80]},
        evidence={"limitation": {"kind": "known_limitation", "subject": detail[:80], "score": 0.15, "detail": detail}})
    if status:
        j.update_objective_sync(o["id"], status=status, note="x", progress={"lesson": lesson})
    return o


def test_template_words_do_not_count():
    words = goal_words("My biggest measured limitation right now: Autonomous development loop: push off by default. Improve it. "
                       "Plan: (1) `research` how comparable systems overcome: Autonomous development loop: push off by default. "
                       "(2) `learn` one verified conclusion with sources.")
    assert words == {"push", "off", "default"}
    assert goal_words("Learn how to do what objective #12 could not: sqlite locking. `research` it and `learn` one verified "
                      "conclusion with sources.") == {"sqlite", "locking"}


def test_same_kind_and_template_alone_no_longer_qualify(tmp_path):
    j = Journal(tmp_path / "j.db")
    old = _limitation(j, "a", "Self-model: performance history is task durations per kind", status="DONE")
    now = _limitation(j, "b", "Autonomous development loop: push off by default")
    assert f"#{old['id']}" not in past_experience(j, now)


def test_same_limitation_subject_qualifies(tmp_path):
    j = Journal(tmp_path / "j.db")
    old = _limitation(j, "a", "Autonomous development loop: push off by default", status="DONE", lesson="pushing needs a remote")
    now = _limitation(j, "b", "Autonomous development loop: push off by default")
    text = past_experience(j, now)
    assert f"#{old['id']} DONE" in text and "pushing needs a remote" in text


def test_three_shared_content_words_qualify_two_do_not(tmp_path):
    j = Journal(tmp_path / "j.db")
    three = j.add_objective_sync("Speed up sqlite journal writes under heavy load", source="human", key="a", check={"kind": "change_released"})
    two = j.add_objective_sync("Compress sqlite journal backups nightly", source="human", key="b", check={"kind": "knowledge_stored", "topic": "zip"})
    for o in (three, two):
        j.update_objective_sync(o["id"], status="DONE", note="x")
    now = j.add_objective_sync("Research why sqlite journal writes stall", source="selfmodel", key="c", check={"kind": "knowledge_stored", "topic": "stall"})
    text = past_experience(j, now)
    assert f"#{three['id']}" in text  # sqlite, journal, writes: another kind, no subject, still similar
    assert f"#{two['id']}" not in text  # sqlite, journal (+ same kind): not enough


def test_failures_rank_before_done(tmp_path):
    j = Journal(tmp_path / "j.db")
    done = [_limitation(j, f"d{i}", "Core: one task at a time; no queue scheduling", status="DONE") for i in range(3)]
    failed = j.add_objective_sync("Add queue scheduling so a task waits instead of being refused", source="human", key="f",
                                  check={"kind": "change_released"})
    j.update_objective_sync(failed["id"], status="DROPPED", note="x", progress={"lesson": "ran out of steps"})
    now = _limitation(j, "n", "Core: one task at a time; no queue scheduling")
    lines = [ln for ln in past_experience(j, now).splitlines() if ln.startswith("- #")]
    assert len(lines) == 3  # the limit holds
    assert lines[0].startswith(f"- #{failed['id']} DROPPED")  # fewer points than the same-subject DONE ones, still first
    assert all(f"#{o['id']}" in "\n".join(lines) for o in done[1:])  # newest same-subject DONE ones fill the rest


def test_words_common_to_the_pool_do_not_count(tmp_path):
    j = Journal(tmp_path / "j.db")
    for i in range(EXPERIENCE_COMMON_MIN_POOL):
        o = j.add_objective_sync(f"Widget gizmo sprocket chore number{i}", source="human", key=f"p{i}", check={"kind": "change_released"})
        j.update_objective_sync(o["id"], status="DONE", note="x")
    now = j.add_objective_sync("Widget gizmo sprocket polish", source="human", key="n", check={"kind": "knowledge_stored", "topic": "polish"})
    assert past_experience(j, now) == ""


def test_output_keeps_its_bounds(tmp_path):
    j = Journal(tmp_path / "j.db")
    for i in range(6):
        _limitation(j, f"d{i}", "Journal: file edits are reality-checked " + "detail " * 40, status="BLOCKED", lesson="L" * 400)
    now = _limitation(j, "n", "Journal: file edits are reality-checked " + "detail " * 40)
    text = past_experience(j, now)
    assert text.startswith("Past experience with similar objectives") and len(text) <= 901
    assert sum(ln.startswith("- #") for ln in text.splitlines()) <= 3
