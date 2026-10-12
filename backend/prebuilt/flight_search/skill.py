"""Flights between two places on a date, read live from Google Flights.

Prebuilt SYRAX skill (feature catalog: flight_finder); the idea came from the
surveyed JARVIS assistants, the code is SYRAX's own. A headless Chrome (the
one SYRAX already finds for its browser, driven by playwright, which is
already a dependency) opens the Google Flights search for the words; each
result row carries a full description in its aria-label, which is parsed
into price, airline, stops, times and layovers. It only reads: it never
signs in, selects a flight or books anything.
"""

import asyncio
import datetime as dt
import re
import urllib.parse
from typing import ClassVar, Dict, List, Optional

from app.tool.base import BaseTool, ToolResult

SEARCH = "https://www.google.com/travel/flights?hl=en&q={q}"
ROW = '[aria-label^="From "]'
LABEL = re.compile(
    r"^From (?P<price>[\d,.]+) (?P<currency>.+?)(?P<round> round trip total)?\. "
    r"(?P<stops>Nonstop|\d+ stops?) flight with (?P<airline>.+?)\. "
    r"Leaves (?P<from>.+?) at (?P<dep>\d{1,2}:\d{2}\s?[AP]M) on (?P<dep_day>.+?) "
    r"and arrives at (?P<to>.+?) at (?P<arr>\d{1,2}:\d{2}\s?[AP]M) on (?P<arr_day>.+?)\. "
    r"Total duration (?P<duration>.+?)\.", re.S)
LAYOVER = re.compile(r"is an? (?P<time>.+?) (?:overnight )?layover at (?P<where>.+?)(?: in [^.]+)?\.")
CABINS = ("economy", "premium economy", "business", "first")
TIMEOUT_S = 75.0


def query(origin: str, destination: str, date: str, return_date: Optional[str] = None,
          adults: int = 1, cabin: Optional[str] = None, today: Optional[dt.date] = None) -> str:
    origin, destination = (origin or "").strip(), (destination or "").strip()
    if not origin or not destination:
        raise ValueError("both origin and destination are needed, e.g. Dhaka and Kolkata")
    today = today or dt.date.today()
    try:
        out = dt.date.fromisoformat(str(date).strip())
        back = dt.date.fromisoformat(str(return_date).strip()) if return_date else None
    except ValueError:
        raise ValueError("dates must be YYYY-MM-DD, e.g. 2026-11-20")
    if out < today:
        raise ValueError(f"{out} is in the past")
    if back and back < out:
        raise ValueError("the return date is before the departure date")
    q = f"Flights from {origin} to {destination} on {out.isoformat()}"
    q += f" returning {back.isoformat()}" if back else " one way"
    adults = max(1, min(int(adults or 1), 9))
    if adults > 1:
        q += f" for {adults} adults"
    if cabin:
        if cabin.lower() not in CABINS:
            raise ValueError("cabin must be economy, premium economy, business or first")
        q += f" {cabin.lower()} class"
    return q


def parse(label: str) -> Optional[Dict[str, str]]:
    m = LABEL.search(" ".join((label or "").split()))
    if not m:
        return None
    f = m.groupdict()
    f["round"] = bool(f["round"])
    f["value"] = float(f["price"].replace(",", ""))
    f["layovers"] = [f"{l['time']} in {l['where']}" for l in LAYOVER.finditer(label)]
    return f


def options(labels: List[str]) -> List[Dict[str, str]]:
    """Parsed rows, each flight once, cheapest first."""
    seen, out = set(), []
    for label in labels:
        f = parse(label)
        if not f:
            continue
        key = (f["airline"], f["dep"], f["dep_day"], f["arr"], f["arr_day"], f["price"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return sorted(out, key=lambda f: f["value"])


def line(i: int, f: Dict[str, str]) -> str:
    stops = "nonstop" if f["stops"] == "Nonstop" else f["stops"]
    via = f" (via {'; '.join(f['layovers'])})" if f["layovers"] else ""
    return (f"{i}. {f['price']} {f['currency']}{' round trip' if f['round'] else ''} · {f['airline']} · {stops}{via} · "
            f"leaves {f['dep']} {f['dep_day']}, arrives {f['arr']} {f['arr_day']} · {f['duration']}")


async def fetch_labels(url: str) -> Dict[str, object]:
    """Open the search in a headless Chrome and return the result rows' aria-labels (and the page text when none)."""
    from playwright.async_api import async_playwright

    from syrax.browser import find_chrome

    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("no Chrome, Edge or Brave was found to read Google Flights with")
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chrome, headless=True)
        try:
            page = await browser.new_page(locale="en-US")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_selector(ROW, timeout=25000)
                await page.wait_for_timeout(1500)  # the list fills in a moment after the first row
            except Exception:
                pass  # no rows: the page text says why
            labels = await page.eval_on_selector_all(ROW, "els => els.map(e => e.getAttribute('aria-label'))")
            text = "" if labels else " ".join((await page.inner_text("body")).split())[:600]
            return {"labels": labels, "text": text, "url": page.url}
        finally:
            await browser.close()


async def search(origin: str, destination: str, date: str, return_date: Optional[str] = None,
                 adults: int = 1, cabin: Optional[str] = None, max_results: int = 8) -> str:
    q = query(origin, destination, date, return_date, adults, cabin)
    url = SEARCH.format(q=urllib.parse.quote(q))
    page = await asyncio.wait_for(fetch_labels(url), TIMEOUT_S)
    found = options(page["labels"])
    if not found:
        raise LookupError(f"Google Flights showed no flights for '{q}'. The page said: {page['text'] or '(nothing)'}")
    shown = found[: max(1, min(int(max_results or 8), 20))]
    head = (f"Google Flights for '{q}': {len(found)} option(s), cheapest first (prices as Google shows them now; "
            f"nothing was booked). Open: {url}")
    return "\n".join([head] + [line(i, f) for i, f in enumerate(shown, 1)])


class Skill(BaseTool):
    name: ClassVar[str] = "flight_search"
    description: ClassVar[str] = ("Live flight options between two cities or airports on a date, read from Google Flights: price, "
                                  "airline, stops, times, layovers, cheapest first. Use it for 'find flights', 'cheapest flight', "
                                  "'flights to X'. It only reads; it never books.")
    risk: ClassVar[str] = "EXTERNAL_READ"
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "origin": {"type": "string", "description": "city or airport code to fly from, e.g. Dhaka or DAC"},
            "destination": {"type": "string", "description": "city or airport code to fly to"},
            "date": {"type": "string", "description": "departure date, YYYY-MM-DD"},
            "return_date": {"type": "string", "description": "return date (YYYY-MM-DD) for a round trip; leave out for one way"},
            "adults": {"type": "integer", "description": "number of adult passengers (default 1)"},
            "cabin": {"type": "string", "enum": list(CABINS)},
            "max_results": {"type": "integer", "description": "how many options to list (default 8)"},
        },
        "required": ["origin", "destination", "date"],
    }

    async def execute(self, origin: str, destination: str, date: str, return_date: Optional[str] = None,
                      adults: int = 1, cabin: Optional[str] = None, max_results: int = 8) -> ToolResult:
        try:
            return ToolResult(output=await search(origin, destination, date, return_date, adults, cabin, max_results))
        except asyncio.TimeoutError:
            return ToolResult(error=f"flight_search: Google Flights did not answer within {int(TIMEOUT_S)}s")
        except Exception as e:
            return ToolResult(error=f"flight_search: {e}")
