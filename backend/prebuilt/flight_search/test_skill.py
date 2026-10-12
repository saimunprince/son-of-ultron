"""flight_search: the words for Google Flights, the result rows parsed (labels
copied from a live page on 2026-10-12), each flight once and cheapest first.
No browser and no network here: fetch_labels is replaced."""

import asyncio
import datetime as dt
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("prebuilt_flight_search_skill", Path(__file__).with_name("skill.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

NONSTOP = ("From 10822 Bangladeshi takas. Nonstop flight with US-Bangla Airlines. Leaves Hazrat Shahjalal International Airport "
           "at 10:00 AM on Friday, November 20 and arrives at Netaji Subhash Chandra Bose International Airport at 10:30 AM "
           "on Friday, November 20. Total duration 1 hr.   Select flight")
ONE_STOP = ("From 140161 Bangladeshi takas. 1 stop flight with Malaysia Airlines. Leaves Hazrat Shahjalal International Airport at "
            "12:30 PM on Friday, November 20 and arrives at Netaji Subhash Chandra Bose International Airport at 11:10 PM on "
            "Friday, November 20. Total duration 11 hr 10 min.  Layover (1 of 1) is a 2 hr 55 min layover at Kuala Lumpur "
            "International Airport in Federal Territory of Kuala Lumpur. Select flight")
LONG = ("From 71921 Bangladeshi takas. 1 stop flight with THAI. Leaves Hazrat Shahjalal International Airport at 1:40 PM on "
        "Friday, November 20 and arrives at Netaji Subhash Chandra Bose International Airport at 4:15 PM on Saturday, November 21. "
        "Total duration 27 hr 5 min.  Layover (1 of 1) is a 22 hr overnight layover at Suvarnabhumi Airport in Bangkok. Select flight")
ROUND = ("From 25,410 Bangladeshi takas round trip total. Nonstop flight with Biman Bangladesh Airlines. Leaves Hazrat Shahjalal "
         "International Airport at 8:00 AM on Friday, November 20 and arrives at Netaji Subhash Chandra Bose International "
         "Airport at 8:30 AM on Friday, November 20. Total duration 1 hr. Select flight")
TODAY = dt.date(2026, 10, 12)


def test_the_words_for_google_flights():
    assert mod.query("Dhaka", "Kolkata", "2026-11-20", today=TODAY) == "Flights from Dhaka to Kolkata on 2026-11-20 one way"
    assert mod.query("DAC", "CCU", "2026-11-20", "2026-11-25", adults=2, cabin="Business", today=TODAY) == (
        "Flights from DAC to CCU on 2026-11-20 returning 2026-11-25 for 2 adults business class")
    for bad, why in ((("", "CCU", "2026-11-20"), "origin and destination"), (("DAC", "CCU", "20/11/2026"), "YYYY-MM-DD"),
                     (("DAC", "CCU", "2026-10-01"), "in the past")):
        with pytest.raises(ValueError, match=why):
            mod.query(*bad, today=TODAY)
    with pytest.raises(ValueError, match="before the departure"):
        mod.query("DAC", "CCU", "2026-11-20", "2026-11-19", today=TODAY)
    with pytest.raises(ValueError, match="cabin"):
        mod.query("DAC", "CCU", "2026-11-20", cabin="sofa", today=TODAY)


def test_a_row_becomes_price_airline_stops_times_and_layovers():
    f = mod.parse(ONE_STOP)
    assert (f["price"], f["currency"], f["stops"], f["airline"]) == ("140161", "Bangladeshi takas", "1 stop", "Malaysia Airlines")
    assert (f["dep"], f["dep_day"], f["arr"], f["duration"]) == ("12:30 PM", "Friday, November 20", "11:10 PM", "11 hr 10 min")
    assert f["layovers"] == ["2 hr 55 min in Kuala Lumpur International Airport"] and not f["round"]
    assert mod.parse(LONG)["layovers"] == ["22 hr in Suvarnabhumi Airport"]
    r = mod.parse(ROUND)
    assert r["round"] and r["value"] == 25410.0 and r["airline"] == "Biman Bangladesh Airlines"
    assert mod.parse("From Price unavailable. Select flight") is None


def test_each_flight_once_cheapest_first():
    found = mod.options([ONE_STOP, NONSTOP, LONG, NONSTOP, ONE_STOP, "Other flights"])
    assert [f["airline"] for f in found] == ["US-Bangla Airlines", "THAI", "Malaysia Airlines"]
    assert mod.line(1, found[0]) == ("1. 10822 Bangladeshi takas · US-Bangla Airlines · nonstop · leaves 10:00 AM Friday, "
                                     "November 20, arrives 10:30 AM Friday, November 20 · 1 hr")
    assert "(via 22 hr in Suvarnabhumi Airport)" in mod.line(2, found[1])


def test_the_skill_reads_the_page_and_never_books(monkeypatch):
    urls = []

    async def fake(url):
        urls.append(url)
        return {"labels": [LONG, NONSTOP, LONG], "text": "", "url": url}

    monkeypatch.setattr(mod, "fetch_labels", fake)
    out = asyncio.run(mod.Skill().execute(origin="Dhaka", destination="Kolkata", date="2099-11-20"))
    assert out.error is None and out.output.startswith("Google Flights for 'Flights from Dhaka to Kolkata on 2099-11-20 one way': 2 option(s)")
    assert "nothing was booked" in out.output and urls[0] in out.output
    assert urls[0].startswith("https://www.google.com/travel/flights?hl=en&q=Flights%20from%20Dhaka")
    assert out.output.splitlines()[1].startswith("1. 10822 Bangladeshi takas · US-Bangla Airlines")


def test_no_rows_or_a_slow_page_is_an_error(monkeypatch):
    async def empty(url):
        return {"labels": [], "text": "No results returned.", "url": url}

    monkeypatch.setattr(mod, "fetch_labels", empty)
    out = asyncio.run(mod.Skill().execute(origin="Dhaka", destination="Atlantis", date="2099-11-20"))
    assert out.error.startswith("flight_search: Google Flights showed no flights for") and "No results returned." in out.error

    async def slow(url):
        await asyncio.sleep(5)

    monkeypatch.setattr(mod, "fetch_labels", slow)
    monkeypatch.setattr(mod, "TIMEOUT_S", 0.05)
    assert "did not answer within" in asyncio.run(mod.Skill().execute(origin="A", destination="B", date="2099-11-20")).error


def test_the_skill_declares_what_it_does():
    s = mod.Skill()
    assert s.name == "flight_search" and s.risk == "EXTERNAL_READ"
    assert s.parameters["required"] == ["origin", "destination", "date"]
