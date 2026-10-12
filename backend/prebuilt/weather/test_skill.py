"""weather: parses Open-Meteo answers into a spoken report; no network in tests."""

import asyncio
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("prebuilt_weather_skill", Path(__file__).with_name("skill.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

GEO = {"results": [{"name": "Dhaka", "admin1": "Dhaka Division", "country": "Bangladesh", "latitude": 23.71, "longitude": 90.41}]}
FC = {
    "current_units": {"temperature_2m": "°C", "wind_speed_10m": "km/h"},
    "current": {"temperature_2m": 29.4, "apparent_temperature": 33.1, "relative_humidity_2m": 78, "precipitation": 0.0,
                "weather_code": 2, "wind_speed_10m": 9.7},
    "daily": {"time": ["2026-10-12", "2026-10-13"], "weather_code": [2, 63], "temperature_2m_min": [25.1, 24.8],
              "temperature_2m_max": [31.0, 29.5], "precipitation_probability_max": [10, 80]},
}


def fake(urls):
    def fetch(url, timeout=15.0):
        urls.append(url)
        return GEO if "geocoding" in url else FC
    return fetch


def test_report_from_live_shaped_answers(monkeypatch):
    urls = []
    monkeypatch.setattr(mod, "fetch_json", fake(urls))
    out = asyncio.run(mod.Skill().execute(place="Dhaka", days=2))
    assert out.error is None
    text = out.output
    assert text.startswith("Dhaka, Dhaka Division, Bangladesh: partly cloudy, 29.4°C (feels like 33.1°C), humidity 78%")
    assert "2026-10-13: rain, 24.8 to 29.5°C, rain chance 80%" in text and text.endswith("Source: Open-Meteo.")
    assert "latitude=23.71" in urls[1] and "forecast_days=2" in urls[1]


def test_days_are_clamped_and_an_unknown_place_is_an_error(monkeypatch):
    urls = []
    monkeypatch.setattr(mod, "fetch_json", fake(urls))
    asyncio.run(mod.Skill().execute(place="Dhaka", days=30))
    assert "forecast_days=7" in urls[-1]
    monkeypatch.setattr(mod, "fetch_json", lambda url, timeout=15.0: {"results": []})
    out = asyncio.run(mod.Skill().execute(place="Nowhereville"))
    assert out.error and "no place called 'Nowhereville'" in out.error
    assert asyncio.run(mod.Skill().execute(place=" ")).error


def test_a_network_failure_is_reported_not_raised(monkeypatch):
    def down(url, timeout=15.0):
        raise OSError("network unreachable")
    monkeypatch.setattr(mod, "fetch_json", down)
    out = asyncio.run(mod.Skill().execute(place="Dhaka"))
    assert out.error == "weather: network unreachable"


def test_the_skill_declares_what_it_does():
    s = mod.Skill()
    assert s.name == "weather" and s.risk == "EXTERNAL_READ" and s.parameters["required"] == ["place"]
