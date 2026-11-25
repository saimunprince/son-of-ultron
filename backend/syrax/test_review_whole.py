"""2026-11-25: brains.fit_request clips a long message to fit a small brain (head and tail kept), so a reviewer with
a small request limit could approve a diff whose middle it never read. Such a brain is skipped; one that can read
the whole diff judges it. The daily ledger was held every day from 11-07: it goes out as two releases now."""

import asyncio

from syrax import brains, ledger
from syrax import review as rv
from syrax.test_review_fallback import GOOD, Router


def diff(chars):
    lines = "".join(f"+line {i} {'x' * 60}\n" for i in range(chars // 70))
    return {"diff": "--- a/x.py\n+++ b/x.py\n@@ -0,0 +1 @@\n" + lines, "stat": "x.py | many +"}


def test_a_small_brain_is_never_asked_to_review_a_diff_it_cannot_read_whole():
    assert brains.PROVIDERS["groq"].max_request_tokens == 8000
    asked = []

    class Spy(Router):
        async def _call(self, pid, messages, tools, choice, images=False):
            asked.append(pid)
            return await super()._call(pid, messages, tools, choice, images)

    v = asyncio.run(rv.review(Spy({"groq": GOOD, "openrouter": GOOD}), diff(40000), "s", ["gemini"]))
    assert "groq" not in asked and v["approve"] is True and v["reviewer"] != "groq"
    small = asyncio.run(rv.review(Spy({"groq": GOOD}), diff(2000), "s", ["gemini"]))
    assert small["approve"] is True


def test_only_small_brains_left_means_no_review():
    v = asyncio.run(rv.review(Router({"groq": GOOD}), diff(40000), "s", ["gemini"]))
    assert v["available"] is False and "too long for this brain" in v["reasons"][0]


def test_publish_all_releases_documents_then_the_matrix(monkeypatch):
    calls = []

    async def fake(journal, **kw):
        calls.append(kw)
        return {"outcome": "COMMITTED"}

    monkeypatch.setattr(ledger, "publish", fake)
    rep = asyncio.run(ledger.publish_all(None, reviewer="r"))
    assert rep["outcome"] == "COMMITTED" and rep["matrix_release"]["outcome"] == "COMMITTED"
    assert calls == [{"reviewer": "r", "matrix": False}, {"reviewer": "r", "force": True, "matrix": True, "docs": False}]
