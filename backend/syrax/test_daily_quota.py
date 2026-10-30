"""EVOLUTION_PLAN wave 3 (directions 235 load balancing, 278 cost-aware routing): a 429 for a spent DAILY quota got the
same 15 s rest as a per-minute burst, so until midnight every request first tried that brain, failed and failed over.
A daily-quota 429 now rests the brain until its quota resets (midnight Pacific for Google, midnight UTC otherwise)."""

import datetime

import httpx
from openai import RateLimitError

from syrax import brains


def limited(message):
    resp = httpx.Response(429, request=httpx.Request("POST", "https://x/v1/chat/completions"), json={"error": {"message": message}})
    return RateLimitError(message, response=resp, body={"error": {"message": message}})


def test_daily_and_burst_limits_are_told_apart():
    assert brains._daily_quota(limited("Quota exceeded for metric: generate_content_free_tier_requests, limit: 250, "
                                       "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"))
    assert brains._daily_quota(limited("Rate limit reached for model on requests per day (RPD): Limit 1000"))
    assert not brains._daily_quota(limited("Rate limit reached on tokens per minute (TPM): Limit 8000"))


def test_the_rest_lasts_until_the_reset():
    pacific_11pm = datetime.datetime(2026, 10, 30, 23, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-7))).timestamp()
    assert abs(brains._until_quota_reset("gemini", pacific_11pm) - 3600) < 2
    utc_noon = datetime.datetime(2026, 10, 30, 12, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert abs(brains._until_quota_reset("groq", utc_noon) - 12 * 3600) < 2


def test_a_spent_daily_quota_rests_the_brain_and_says_why(monkeypatch, tmp_path):
    r = brains.BrainRouter()
    r._penalize("groq", limited("requests per day (RPD): Limit 1000, Used 1000"), "rate limited")
    h = r.health["groq"]
    assert h.until - brains.time.time() > 60 and "daily quota spent" in h.reason
    r._penalize("gemini", limited("tokens per minute"), "rate limited")
    assert r.health["gemini"].until - brains.time.time() <= 16


def test_a_pooled_provider_rests_the_spent_model_not_itself():
    assert brains.PROVIDERS["gemini"].pool
    daily = limited("quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    assert brains._model_rest("gemini", daily, False) > 60
    assert brains._model_rest("gemini", limited("per minute"), False) <= brains.POOL_MODEL_COOLDOWN_S
    r = brains.BrainRouter()
    r._penalize("gemini", daily, "rate limited")  # every pooled model was out: the provider rest stays short
    assert r.health["gemini"].until - brains.time.time() <= 16
