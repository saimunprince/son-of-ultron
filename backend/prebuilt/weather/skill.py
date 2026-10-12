"""Current weather and a short forecast for a place, from Open-Meteo (free, no key).

Prebuilt SYRAX skill. The idea comes from the JARVIS assistants surveyed on
2026-10-12 (theirs only opened a browser search); this is SYRAX's own code.
"""

import asyncio
import json
import urllib.parse
import urllib.request
from typing import ClassVar, Optional

from app.tool.base import BaseTool, ToolResult

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=en&format=json"
FORECAST = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            "&timezone=auto&forecast_days={days}")
CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "heavy rain showers", 82: "violent rain showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def fetch_json(url: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "SYRAX-weather/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def condition(code) -> str:
    try:
        return CODES.get(int(code), f"weather code {code}")
    except (TypeError, ValueError):
        return "unknown"


def report(place: dict, data: dict) -> str:
    name = ", ".join(x for x in (place.get("name"), place.get("admin1"), place.get("country")) if x)
    cur, units = data.get("current") or {}, data.get("current_units") or {}
    deg = units.get("temperature_2m", "°C")
    lines = [f"{name}: {condition(cur.get('weather_code'))}, {cur.get('temperature_2m')}{deg} "
             f"(feels like {cur.get('apparent_temperature')}{deg}), humidity {cur.get('relative_humidity_2m')}%, "
             f"wind {cur.get('wind_speed_10m')} {units.get('wind_speed_10m', 'km/h')}, precipitation {cur.get('precipitation')} mm."]
    d = data.get("daily") or {}
    for i, day in enumerate(d.get("time") or []):
        rain = (d.get("precipitation_probability_max") or [None] * (i + 1))[i]
        lines.append(f"{day}: {condition((d.get('weather_code') or [None] * (i + 1))[i])}, "
                     f"{(d.get('temperature_2m_min') or [None] * (i + 1))[i]} to {(d.get('temperature_2m_max') or [None] * (i + 1))[i]}{deg}"
                     + (f", rain chance {rain}%" if rain is not None else ""))
    lines.append("Source: Open-Meteo.")
    return "\n".join(lines)


def weather(place: str, days: int = 3) -> str:
    q = (place or "").strip()
    if not q:
        raise ValueError("a place is required, e.g. Dhaka")
    days = max(1, min(int(days or 3), 7))
    found = (fetch_json(GEOCODE.format(q=urllib.parse.quote(q))).get("results") or [])
    if not found:
        raise LookupError(f"no place called {q!r} was found")
    p = found[0]
    data = fetch_json(FORECAST.format(lat=p["latitude"], lon=p["longitude"], days=days))
    return report(p, data)


class Skill(BaseTool):
    name: ClassVar[str] = "weather"
    description: ClassVar[str] = ("Current weather and a forecast (1-7 days) for a city or place, live from Open-Meteo. "
                                  "Use it instead of guessing or opening a browser.")
    risk: ClassVar[str] = "EXTERNAL_READ"
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "place": {"type": "string", "description": "City or place name, e.g. 'Dhaka' or 'London, UK'"},
            "days": {"type": "integer", "description": "Forecast days, 1-7 (default 3)"},
        },
        "required": ["place"],
    }

    async def execute(self, place: str, days: Optional[int] = 3) -> ToolResult:
        try:
            return ToolResult(output=await asyncio.to_thread(weather, place, days or 3))
        except Exception as e:
            return ToolResult(error=f"weather: {e}")
