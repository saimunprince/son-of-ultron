"""M2: a brain that never answers its first case is not run through the rest
(live 2026-10-11: three such brains spent 12 tasks of another brain's free
quota), and nothing unmeasured becomes an experiment row."""

import asyncio

from syrax import codebench
from syrax.journal import Journal
from syrax.test_codebench import CASES, FakeCore


def test_a_brain_that_never_answers_stops_after_its_first_case(tmp_path):
    j = Journal(tmp_path / "j.db")
    core = FakeCore(j, ["alpha", "groq", "beta"], skill={"alpha": set(CASES), "beta": set(CASES)}, failover={"groq": "alpha"})
    res = asyncio.run(codebench.run_all(core, ws=tmp_path / "ws"))
    assert [c for b, c in core.submitted if b == "groq"] == ["fix_word_count"]
    groq = next(r for r in res["runs"] if r["brain"] == "groq")
    assert groq["never_answered"] and groq["graded"] == 0 and len(groq["skipped"]) == len(CASES) - 1
    assert [e["hypothesis"] for e in j.experiments(limit=10)] == ["brain beta finishes code changes at least as well as alpha"]
    assert codebench.summary(res) == "alpha 4/4, groq never answered, beta 4/4"


def test_a_brain_that_answered_part_of_its_work_is_still_run_through(tmp_path):
    j = Journal(tmp_path / "j.db")

    class Partial(FakeCore):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            real = self.journal.start_task_sync

            def start(goal, **kw2):  # beta answers one step of each task itself, then fails over
                t = real(goal, **kw2)
                if self.agent.llm.preferred == "beta":
                    self.journal.record_sync("brain.answered", {"provider": "beta"}, task_id=t)
                return t

            self.journal.start_task_sync = start

    core = Partial(j, ["alpha", "beta"], skill={"alpha": set(CASES)}, failover={"beta": "alpha"})
    res = asyncio.run(codebench.run_all(core, ws=tmp_path / "ws"))
    beta = next(r for r in res["runs"] if r["brain"] == "beta")
    assert not beta["never_answered"] and beta["skipped"] == [] and len(beta["not_measured"]) == len(CASES)
    assert j.experiments(limit=5)[0]["verdict"] == "INCONCLUSIVE"  # tried, but too little of its own
