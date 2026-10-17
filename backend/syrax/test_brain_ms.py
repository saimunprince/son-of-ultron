import time

from syrax.journal import Journal
from syrax.selfmodel import SelfModel
from syrax.test_brains import ask, base, router  # noqa: F401  (pytest fixtures and a helper)


def test_an_answer_carries_its_milliseconds(router):
    seen = []

    async def listen(event):
        seen.append(event)

    router.listeners.add(listen)
    ask(router)
    answered = [e for e in seen if e.get("event") == "answered"]
    assert answered and isinstance(answered[0]["ms"], int) and answered[0]["ms"] >= 0


def test_performance_reports_brain_ms_per_provider(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work", kind="conversation")
    for ms in (100, 300, 500):
        j.record_sync("brain.answered", {"event": "answered", "provider": "gemini", "ms": ms}, task_id=t)
    j.record_sync("brain.answered", {"event": "answered", "provider": "openrouter", "ms": 2000}, task_id=t)
    j.record_sync("brain.answered", {"event": "answered", "provider": "upstage"}, task_id=t)
    assert SelfModel(j).performance()["brain_ms"] == {"gemini": {"count": 3, "p50": 300, "p90": 500},
                                                     "openrouter": {"count": 1, "p50": 2000, "p90": 2000}}
