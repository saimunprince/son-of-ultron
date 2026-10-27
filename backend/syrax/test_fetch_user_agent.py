"""2026-10-27 review of the logs: 92 "Failed to fetch content" lines since 10-10 (69 x HTTP 403; en.wikipedia.org 21,
stackoverflow 7). The page fetcher `research` uses put its browser string under the header "WebSearch", so requests
sent its default python-requests agent; Wikipedia answered 403 to that and 200 to the browser string (checked live the
same day). The fetcher now sends it as the User-Agent."""

import asyncio

import requests

from app.tool.web_search import WebContentFetcher


class Page:
    status_code = 200
    text = "<html><body><p>Ethanol boils at 78.37 C.</p></body></html>"


def test_the_page_fetch_sends_a_browser_user_agent(monkeypatch):
    sent = {}

    def fake_get(url, headers=None, timeout=None):
        sent.update(headers or {})
        return Page()

    monkeypatch.setattr(requests, "get", fake_get)
    text = asyncio.run(WebContentFetcher.fetch_content("https://en.wikipedia.org/wiki/Ethanol"))
    assert sent.get("User-Agent", "").startswith("Mozilla/5.0")
    assert "WebSearch" not in sent
    assert text and "78.37" in text
