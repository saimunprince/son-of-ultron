"""2026-11-04 (quality run #22): Gemini's free quota ran out mid-suite. SYRAX's own background work and small talk try
a lighter brain first; the human's real requests, evals and code changes keep the human's order."""

from syrax import routing

ORDER = ["gemini", "groq", "ollama"]


def ok(pid):
    return True, ""


def test_background_work_and_small_talk_go_light():
    assert routing.quota_saver("autonomous", "other", ORDER, ok) == "groq"
    assert routing.quota_saver("conversation", "chat", ORDER, ok) == "groq"


def test_real_requests_evals_keep_the_order():
    assert routing.quota_saver("conversation", "code", ORDER, ok) is None
    assert routing.quota_saver("conversation", "research", ORDER, ok) is None
    assert routing.quota_saver("eval", "chat", ORDER, ok) is None


def test_no_saver_when_it_is_unavailable_or_already_first():
    assert routing.quota_saver("autonomous", "other", ORDER, lambda p: (False, "cooling down")) is None
    assert routing.quota_saver("autonomous", "other", ["groq", "gemini"], ok) is None
    assert routing.quota_saver("autonomous", "other", ["gemini", "ollama"], ok) is None
