"""2026-10-27: NOAA's products/solar-wind/plasma-1-day.json answers 404 (the whole folder is gone) and the Kp product
now sends objects ({"time_tag", "Kp", ...}) where the HUD read row[1]. The solar wind comes from json/rtsw (1-minute
objects, newest first, ~2.4 MB); the core proxy hands the HUD the table it always read, oldest first, trimmed."""

import json

import httpx
from fastapi.testclient import TestClient

from syrax import server

RTSW = [  # newest first, as NOAA sends it; one reading without a speed
    {"time_tag": f"2026-10-27T09:{59 - i:02d}:00", "proton_density": 5.0 + i, "proton_speed": 400 + i, "proton_temperature": 70000, "active": i == 0}
    for i in range(200)
] + [{"time_tag": "2026-10-27T06:00:00", "proton_density": 1.0, "proton_speed": None, "proton_temperature": 1}]
KP = [{"time_tag": "2026-10-27T03:00:00", "Kp": 2.33, "a_running": 9, "station_count": 8},
      {"time_tag": "2026-10-27T06:00:00", "Kp": 3.0, "a_running": 15, "station_count": 8}]


def serve(monkeypatch, bodies):
    calls = []

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            calls.append(url)
            return httpx.Response(200, content=json.dumps(bodies[url]).encode(), request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    server._hud_feed_cache.clear()
    server._hud_feed_failures.clear()
    return TestClient(server.app), calls


def test_the_solar_wind_comes_from_rtsw_as_the_table_the_hud_reads(monkeypatch):
    assert server.HUD_FEEDS["solar"] == "https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json"
    c, calls = serve(monkeypatch, {server.HUD_FEEDS["solar"]: RTSW})
    table = c.get("/hud/feed/solar").json()
    assert table[0] == ["time_tag", "proton_density", "proton_speed", "proton_temperature"]
    rows = table[1:]
    assert len(rows) == server.HUD_SOLAR_ROWS
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)  # oldest first: the HUD takes the last row as now
    assert rows[-1] == ["2026-10-27T09:59:00", 5.0, 400, 70000] and all(r[2] is not None for r in rows)


def test_kp_objects_become_the_table_the_hud_reads(monkeypatch):
    c, _ = serve(monkeypatch, {server.HUD_FEEDS["kp"]: KP})
    table = c.get("/hud/feed/kp").json()
    assert table[0][:2] == ["time_tag", "Kp"] and table[-1][1] == 3.0  # hud.html: +k[k.length - 1][1]


def test_a_table_from_upstream_passes_unchanged(monkeypatch):
    old = [["time_tag", "density", "speed"], ["t", 1, 400]]
    c, _ = serve(monkeypatch, {server.HUD_FEEDS["solar"]: old})
    assert c.get("/hud/feed/solar").json() == old
