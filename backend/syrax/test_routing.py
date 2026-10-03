"""Phase 7: a brain per kind of work, only when measured quality says so."""

from syrax import routing
from syrax.journal import Journal
from syrax.test_brains import BEHAVIOR, SEEN, ask, base, router  # noqa: F401  (fixtures)


def test_kinds_of_work():
    assert routing.kind_of("Reply with the single word: ready") == "chat"
    assert routing.kind_of("What is the capital of Japan?") == "chat"
    assert routing.kind_of("In the file counter.py change count = 1 to count = 2") == "code"
    assert routing.kind_of("Research in what year SQLite was first released and cite a source") == "research"
    assert routing.kind_of("Using the desktop tool, report how many CPU cores this machine has") == "desktop"


def graded(j, goal, brain, ok):
    t = j.start_task_sync(goal, kind="eval")
    j.record_sync("brain.answered", {"provider": brain, "model": "m"}, task_id=t)
    return {"id": goal[:10], "ok": ok, "task_id": t}


def journal_with(tmp_path, alpha_ok, beta_ok, n=6, goal="Reply with the single word: ready"):
    routing.clear_cache()
    j = Journal(tmp_path / "j.db")
    results = [graded(j, goal, "alpha", i < alpha_ok) for i in range(n)] + [graded(j, goal, "beta", i < beta_ok) for i in range(n)]
    j.add_quality_run_sync(results, 50.0, "PASS", brain="alpha,beta")
    return j


def test_a_clearly_better_brain_goes_first_for_its_kind_only(tmp_path):
    j = journal_with(tmp_path, alpha_ok=2, beta_ok=6)
    assert routing.preferred(j, "chat", ["alpha", "beta"]) == "beta"
    assert routing.preferred(j, "code", ["alpha", "beta"]) is None  # nothing measured for code
    assert routing.preferred(j, "chat", ["beta", "alpha"]) is None  # already first
    assert routing.table(j)["chat"]["beta"] == {"graded": 6, "ok": 6, "quality": 0.88}


def test_thin_or_close_evidence_keeps_the_humans_order(tmp_path):
    assert routing.preferred(journal_with(tmp_path / "a", alpha_ok=1, beta_ok=4, n=4), "chat", ["alpha", "beta"]) is None  # < MIN_GRADED
    assert routing.preferred(journal_with(tmp_path / "b", alpha_ok=5, beta_ok=6), "chat", ["alpha", "beta"]) is None  # gap too small


def test_the_router_tries_the_routed_brain_first_and_an_explicit_choice_wins(router):
    router.routed = "beta"
    ask(router)
    assert SEEN[0][0] == "beta"
    SEEN.clear()
    router.preferred = "alpha"  # a brain comparison names its brain explicitly
    ask(router)
    assert SEEN[0][0] == "alpha"
