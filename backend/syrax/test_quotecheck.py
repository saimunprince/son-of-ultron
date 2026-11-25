"""Quote and citation check of a researched answer (quotecheck.verify, Researcher.verify_answer). No network: the
search engine and fetcher are fakes, the journal is real."""

import asyncio

from syrax import quotecheck, research
from syrax.journal import Journal
from syrax.quotecheck import REMOVED, SNIPPET_MARK, match, verify
from syrax.research import Researcher, Source, render_report

PAGE = ("SQLite write-ahead logging. With synchronous=FULL in WAL mode an additional sync of the WAL file happens "
        "after each transaction commit, which makes transactions durable across a power loss.")
SNIPPET = "SQLite was first released in August 2000 by D. Richard Hipp."

SOURCES = [
    {"n": 1, "url": "https://sqlite.org/wal.html", "text": PAGE, "fetched": True, "knowledge_id": 11},
    {"n": 2, "url": "https://example.com/history", "text": SNIPPET, "fetched": False, "knowledge_id": 12},
]


def test_exact_quote_passes_untouched_but_for_the_footer():
    text = 'WAL syncs on commit: "an additional sync of the WAL file happens after each transaction commit" [1].'
    out, c = verify(text, SOURCES)
    assert (c.exact, c.partial, c.missing) == (1, 0, 0)
    assert out.startswith(text)
    assert out.endswith("Quotes checked: 1 exact, 0 partial, 0 not found and removed.")


def test_partial_quote_case_punctuation_and_fuzzy():
    assert match("Makes Transactions durable, across a power-loss", PAGE) == "partial"
    # one word changed out of many: a close in-order match is partial, not missing
    assert match("an additional sync of the WAL file occurs after each transaction commit", PAGE) == "partial"
    # an ellipsis joins two real pieces
    assert match("With synchronous=FULL in WAL mode ... durable across a power loss", PAGE) == "exact"
    out, c = verify('It says "makes transactions DURABLE across a power loss" (https://sqlite.org/wal.html).', SOURCES)
    assert c.partial == 1 and "DURABLE" in out


def test_missing_quote_is_removed_never_left_as_sourced():
    text = 'The docs say "WAL mode is always slower than rollback journals" [1].'
    out, c = verify(text, SOURCES)
    assert c.missing == 1
    assert "always slower" not in out and REMOVED in out
    assert "1 not found and removed" in out
    # a quote pinned on the wrong page is missing too, though another page holds it
    out, c = verify('"first released in August 2000 by D." [1]', SOURCES)
    assert c.missing == 1


def test_broken_citation_becomes_question_mark_and_is_counted():
    text = 'Durable on commit [1][7]. Released in 2000 [9].'
    out, c = verify(text, SOURCES)
    assert c.broken == 2
    assert "[7]" not in out and "[9]" not in out and out.count("[?]") == 2
    assert "2 broken citations" in out
    # a quote resting only on a broken number has no source: removed
    out, c = verify('"an additional sync of the WAL file" [5]', SOURCES)
    assert c.missing == 1 and c.broken == 1 and REMOVED in out


def test_snippet_only_finding_is_marked():
    text = "SQLite first came out in 2000 [2].\nFULL is durable [1][2]."
    out, c = verify(text, SOURCES)
    assert c.snippet_only == 1
    first, second = out.split("\n")[:2]
    assert first == "SQLite first came out in 2000 [2]" + SNIPPET_MARK + "."
    assert SNIPPET_MARK not in second  # an opened page backs the second
    assert "1 finding rests on a search snippet only" in out


def test_footer_counts_everything_and_short_quotes_are_terms():
    text = ('- "an additional sync of the WAL file happens" [1]\n'
            '- "makes transactions durable across a power-loss" [1]\n'
            '- "WAL is a lie told by vendors" [1]\n'
            '- the "WAL file" term [1]\n'
            '- see [4]')
    out, c = verify(text, SOURCES)
    assert out.rstrip().split("\n")[-1] == "Quotes checked: 1 exact, 1 partial, 1 not found and removed; 1 broken citation."
    assert '"WAL file"' in out  # two words: a term, not a finding


def test_no_sources_or_nothing_cited_leaves_the_answer_alone():
    text = 'He said "this is a long enough quote" [1].'
    assert verify(text, []) == (text, quotecheck.Checked())
    out, c = verify("A plain answer with no citations.", SOURCES)
    assert out == "A plain answer with no citations." and not c.footer()
    # a quote citing only a URL no research call read is not judged
    out, c = verify('"some words from another page here" https://other.org/x', SOURCES)
    assert c.unchecked == 1 and REMOVED not in out


# ——— Researcher: task-wide numbers, the check against what was read, the journal ———


def _researcher(tmp_path, monkeypatch, results, pages):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("quote check test")
    monkeypatch.setattr(research, "ENGINES", [lambda q, n: [Source(url=u, snippet=sn, engine="fake") for u, sn in results][:n]])

    async def fetch(url):
        return pages.get(url)
    return j, t, Researcher(j, task_id_provider=lambda: t, fetcher=fetch)


def test_researcher_verifies_answer_and_journals(tmp_path, monkeypatch):
    j, t, r = _researcher(tmp_path, monkeypatch,
                          [("https://sqlite.org/wal.html", "wal"), ("https://example.com/history", SNIPPET)],
                          {"https://sqlite.org/wal.html": PAGE})
    rep = asyncio.run(r.research("sqlite WAL synchronous FULL durable commit released"))
    assert [s["n"] for s in rep["sources"]] == [1, 2]
    assert "[2] knowledge_id" in render_report(rep)
    answer = ('FULL syncs "the WAL file happens after each transaction commit" [1]. '
              'It was "first released in 1999 by a large company" [2]. See also [3].')
    out, c = asyncio.run(r.verify_answer(answer))
    assert (c.exact, c.missing, c.broken, c.snippet_only) == (1, 1, 1, 0)
    assert "1999" not in out and "[?]" in out
    ev = [e for e in j.recent_events(50) if e["type"] == "research.verified"]
    assert ev and ev[0]["payload"]["missing"] == 1 and ev[0]["payload"]["footer"].startswith("Quotes checked:")


def test_numbers_continue_across_calls_in_one_task(tmp_path, monkeypatch):
    j, t, r = _researcher(tmp_path, monkeypatch, [("https://a.org/1", "alpha beta gamma delta")], {})
    asyncio.run(r.research("alpha beta"))
    monkeypatch.setattr(research, "ENGINES", [lambda q, n: [Source(url="https://b.org/2", snippet="epsilon zeta eta theta", engine="fake"),
                                                             Source(url="https://a.org/1", snippet="alpha beta gamma delta", engine="fake")]])
    rep = asyncio.run(r.research("epsilon zeta"))
    assert [s["n"] for s in rep["sources"]] == [2, 1]  # a page read again keeps its number
    out, c = asyncio.run(r.verify_answer("Zeta follows epsilon [2]."))
    assert c.snippet_only == 1 and SNIPPET_MARK in out  # neither page was opened


def test_task_that_researched_nothing_is_not_touched(tmp_path, monkeypatch):
    j, t, r = _researcher(tmp_path, monkeypatch, [], {})
    out, c = asyncio.run(r.verify_answer('"made up words in quotes here" [1]'))
    assert out == '"made up words in quotes here" [1]' and not c.footer()
    assert not [e for e in j.recent_events(50) if e["type"] == "research.verified"]
