"""Live 2026-10-15 (objective 237): SYRAX's first own change to pass the full
gate was rolled back unreviewed: the review asked only the first two other
brains (openrouter, upstage), both failed, while groq and pollinations were
ready. And the release answered the agent with "None" instead of the reason.
Every other usable brain is asked now, and the reasons reach the agent."""

import asyncio

from syrax import devloop
from syrax.review import review

GOOD = '{"weakens_checks": false, "clear_bug": false, "secret": false, "matches_summary": true, "reasons": []}'


class Msg:
    def __init__(self, content):
        self.content = content


class Store:
    order = ["gemini", "openrouter", "upstage", "ollama", "groq", "pollinations"]

    def enabled(self, p):
        return True


class Router:
    store = Store()

    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def usable(self, pid):
        return (False, "cooldown: rate limited") if pid == "ollama" else (True, "ready")

    async def _call(self, pid, messages, tools, choice, images=False):
        self.asked.append(pid)
        a = self.answers.get(pid)
        if isinstance(a, Exception):
            raise a
        return Msg(a)


INFO = {"diff": "--- a/x\n+++ b/x\n", "stat": "x | 1 +"}


def test_the_review_goes_on_past_two_failed_brains():
    r = Router({"openrouter": ConnectionError("Connection error."), "upstage": ConnectionError("Connection error."), "groq": GOOD})
    v = asyncio.run(review(r, INFO, "summary", ["gemini"]))
    assert v["approve"] is True and v["reviewer"] == "groq"
    assert r.asked == ["openrouter", "upstage", "groq"]  # ollama cooling down is not asked
    assert v["unavailable"] == ["openrouter: Connection error.", "upstage: Connection error.", "ollama: cooldown: rate limited"]


def test_no_readable_review_names_every_brain_tried():
    r = Router({"openrouter": ConnectionError("down"), "upstage": "looks fine", "groq": ConnectionError("413"), "pollinations": "ok!"})
    v = asyncio.run(review(r, INFO, "summary", ["gemini"]))
    assert v["approve"] is False and v["problems"] == ["no_review"]
    for part in ("openrouter: down", "upstage: unreadable review", "ollama: cooldown", "groq: 413", "pollinations: unreadable review"):
        assert part in v["reasons"][0]


def report(review_verdict):
    return {"outcome": "REVIEW_REJECTED", "verification_id": 26, "verification": "GREEN", "files": {"backend/syrax/memory.py": "M"},
            "gates": [{"name": "pytest", "status": "PASS"}], "review": review_verdict, "snapshot": "rb/1-58aef24.patch",
            "rollback": {"restored": ["backend/syrax/memory.py"], "removed": ["backend/syrax/test_memory_expiry.py"], "clean": True}}


def test_the_agent_reads_why_the_review_rolled_it_back():
    unreviewed = devloop.render(report({"approve": False, "problems": ["no_review"], "reasons": ["no readable review (upstage: Connection error.)"]}))
    assert "None" not in unreviewed and "upstage: Connection error." in unreviewed and "apply the same change again and release again" in unreviewed
    rejected = devloop.render(report({"approve": False, "problems": ["weakens_checks"], "reasons": ["removes the expiry assert"], "reviewer": "groq"}))
    assert "a second brain (groq) rejected the change (weakens_checks): removes the expiry assert" in rejected and "None" not in rejected
