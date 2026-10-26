"""A rounded figure is the same figure, not a contradiction (live 2026-10-19..26:
"approximately 78.4°C (173.1°F)" against the stored "78.37°C" opened three
contradiction objectives that re-researched, stored more rows and never settled).
Figures that really differ (78.4 vs 82, 2000 vs 2004) still contradict."""

import asyncio

import pytest

from syrax import consolidate
from syrax.journal import Journal
from syrax.research import LearnTool

STORED = "The boiling point of ethanol at sea level is 78.37°C."
ROUNDED = "The boiling point of ethanol at sea level is approximately 78.4°C (173.1°F)."


def setup(tmp_path):
    j = Journal(tmp_path / "j.db")
    web = j.add_knowledge_sync(
        "The boiling point of ethanol at sea level (standard atmospheric pressure) is 78.37 °C, about 173.1 °F; "
        "the library holds 1,442 manuscripts and SQLite was first released in August 2000.",
        "web", source_url="https://example.org/facts", tags=["ethanol"])
    return j, LearnTool(journal=j), web["id"]


def learn(tool, claim, src):
    return asyncio.run(tool.execute(claim=claim, sources=[src]))


def conclusions(j):
    return [k for k in j.knowledge_recent(limit=50) if k["kind"] == "conclusion"]


def contradictions(j):
    return [e for e in j.recent_events(200) if e["type"] == "knowledge.contradiction"]


def test_the_live_pair_is_a_duplicate_not_a_contradiction(tmp_path):
    j, tool, src = setup(tmp_path)
    first = learn(tool, STORED, src).output
    assert first.startswith("Learned id=")
    stored = conclusions(j)[0]
    duplicate, conflicts = consolidate.compare(ROUNDED, j)
    assert conflicts == [] and duplicate is not None and duplicate["id"] == stored["id"]
    out = learn(tool, ROUNDED, src).output
    assert "Already known as id=" in out and "reinforced" in out and "CONTRADICTS" not in out
    assert len(conclusions(j)) == 1 and contradictions(j) == []


def test_the_live_pair_the_other_way_round_reinforces_too(tmp_path):
    j, tool, src = setup(tmp_path)
    learn(tool, ROUNDED, src)
    out = learn(tool, STORED, src).output
    assert "Already known as id=" in out and "CONTRADICTS" not in out
    assert len(conclusions(j)) == 1 and contradictions(j) == []


def test_thousands_separators_are_one_figure(tmp_path):
    assert consolidate.figures("The library holds 1,442 manuscripts.") == {"1442"}
    assert consolidate.figures("It costs 12,345.67 dollars.") == {"12345.67"}
    assert consolidate.figures("SQLite was first released in August 2000, in version 1.0.") == {"2000", "1.0"}
    j, tool, src = setup(tmp_path)
    learn(tool, "The library holds 1,442 manuscripts.", src)
    out = learn(tool, "The library holds 1442 manuscripts.", src).output
    assert "Already known as id=" in out and "CONTRADICTS" not in out


@pytest.mark.parametrize("a, b", [
    ("78.37", "78.4"),        # the live pair: rounds to one decimal
    ("78.4", "78.37"),        # either order
    ("78.37", "78"),          # rounds to a whole number
    ("173.07", "173.1"),
    ("78.35", "78.4"),        # half up
    ("1,442", "1442"),        # thousands separator
    ("1442.3", "1442"),
    ("78.37", "78.29"),       # 0.1 %: sources that differ in the last digits
    ("1442.0", "1442"),
])
def test_rounded_figures_agree(a, b):
    assert consolidate.agree(a, b) and consolidate.agree(b, a)


@pytest.mark.parametrize("a, b", [
    ("78.4", "82"),
    ("78.37", "82.0"),
    ("78.4", "79"),           # 78.4 rounds to 78, and 0.76 % apart
    ("2000", "2004"),         # years are exact even though 0.2 % apart
    ("1442", "1443"),         # counts are exact
    ("1,442", "1,443"),
    ("3.12", "3.13"),         # small decimals (versions, ratios): only rounding counts
    ("100", "100.6"),         # 100.6 rounds to 101, and 0.6 % apart
])
def test_different_figures_do_not_agree(a, b):
    assert not consolidate.agree(a, b) and not consolidate.agree(b, a)


@pytest.mark.parametrize("stored, new", [
    (STORED, "The boiling point of ethanol at sea level is 82°C."),
    (ROUNDED, "The boiling point of ethanol at sea level is approximately 82°C (179.6°F)."),
    ("SQLite was first released in August 2000.", "SQLite was first released in August 2004."),
    ("The library holds 1,442 manuscripts.", "The library holds 1,443 manuscripts."),
])
def test_real_contradictions_are_still_flagged(tmp_path, stored, new):
    j, tool, src = setup(tmp_path)
    learn(tool, stored, src)
    out = learn(tool, new, src).output
    assert "CONTRADICTS" in out
    assert len(conclusions(j)) == 2 and len(contradictions(j)) == 1
