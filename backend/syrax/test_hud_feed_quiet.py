"""Review 2026-10-27: NOAA answers 404 for the solar-wind plasma feed the HUD draws, and every HUD poll went upstream
again and wrote a warning. A failing feed now fails quietly: the HUD gets a 502 (it shows no data), upstream is asked
again only after HUD_FEED_RETRY_S, and the log says so once an hour per feed."""

from fastapi.testclient import TestClient

from syrax import server


class Log:
    def __init__(self):
        self.lines = []

    def warning(self, text):
        self.lines.append(text)

    def __getattr__(self, name):
        return lambda *a, **kw: None


def test_a_feed_that_answers_404_is_logged_once_an_hour_and_not_asked_on_every_poll(monkeypatch):
    import httpx

    calls = []

    class Gone:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            calls.append(url)
            return httpx.Response(404, content=b"not found", request=httpx.Request("GET", url))

    log = Log()
    monkeypatch.setattr(httpx, "AsyncClient", Gone)
    monkeypatch.setattr(server, "logger", log)
    server._hud_feed_cache.clear()
    getattr(server, "_hud_feed_failures", {}).clear()
    c = TestClient(server.app)
    assert [c.get("/hud/feed/solar").status_code for _ in range(5)] == [502] * 5  # the HUD shows no data
    assert len(calls) == 1 and len(log.lines) == 1  # one upstream call and one log line for five polls
    when, logged = server._hud_feed_failures["solar"]
    server._hud_feed_failures["solar"] = (when - server.HUD_FEED_RETRY_S, logged)  # ten minutes later
    assert c.get("/hud/feed/solar").status_code == 502
    assert len(calls) == 2 and len(log.lines) == 1  # asked again, still quiet within the hour
    when, logged = server._hud_feed_failures["solar"]
    server._hud_feed_failures["solar"] = (when - server.HUD_FEED_RETRY_S, logged - server.HUD_FEED_LOG_S)  # an hour on
    assert c.get("/hud/feed/solar").status_code == 502
    assert len(calls) == 3 and len(log.lines) == 2 and "solar" in log.lines[-1]
    server._hud_feed_failures.clear()
