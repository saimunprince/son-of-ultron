"""Knowledge rows keep their own state (audit 2026-10-27, item 4): status ACTIVE / DISPUTED / SUPERSEDED,
verified_at and superseded_by on the `knowledge` row itself.

Before: DISPUTED was recomputed by `know` from the last 3000 events, so an old contradiction aged out and the rows
read as plain fact again; nothing ever settled a dispute; and a memory correction overwrote the row, leaving only
the first 160 characters of the old text in an event. Now a contradiction marks the rows DISPUTED, a later `learn`
with independent evidence settles it (the loser SUPERSEDED, superseded_by the winner), a correction keeps the old
text as a SUPERSEDED row, and readers skip SUPERSEDED rows and mark DISPUTED ones. An old journal migrates in place:
same rows, same ids, every row ACTIVE."""

import asyncio
import json
import sqlite3
import time

import pytest

from syrax import consolidate, research
from syrax.journal import Journal, JournalError, get_journal
from syrax.memory import CorrectRefused, MemoryStore, RecallTool
from syrax.research import KnowTool, LearnTool, Researcher, Source

# the knowledge table as journal.py created it before this change (b0ff07c)
OLD_KNOWLEDGE = """
CREATE TABLE knowledge (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  claim        TEXT NOT NULL,
  kind         TEXT NOT NULL CHECK (kind IN ('web','local','experiment','human','conclusion')),
  source_url   TEXT,
  source_title TEXT,
  excerpt      TEXT,
  confidence   REAL NOT NULL,
  basis        TEXT NOT NULL,
  sources      TEXT NOT NULL,
  tags         TEXT NOT NULL,
  question     TEXT,
  task_id      TEXT,
  created      REAL NOT NULL,
  last_used    REAL,
  uses         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX knowledge_created ON knowledge(created);
"""


def learn(j, claim, *sources):
    return asyncio.run(LearnTool(journal=j).execute(claim=claim, sources=list(sources))).output


def know(j, query):
    return asyncio.run(KnowTool(journal=j).execute(query=query)).output


def events(j, type_):
    return [e["payload"] for e in j.recent_events(5000) if e["type"] == type_]


def web(j, text, url):
    return j.add_knowledge_sync(text, "web", source_url=url, excerpt=text, tags=["sqlite"])["id"]


def disputed_pair(tmp_path):
    j = Journal(tmp_path / "j.db")
    src = web(j, "SQLite 1.0 was released in August 2000; some pages say 2004.", "https://example.org/a")
    learn(j, "SQLite was first released in August 2000.", src)
    learn(j, "SQLite was first released in August 2004.", src)
    a, b = j.knowledge_of_kind(("conclusion",))
    return j, src, a["id"], b["id"]


# ——— migration ———


def test_an_old_journal_opens_with_every_row_kept_and_active(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript(OLD_KNOWLEDGE)
    rows = [
        ("SQLite 1.0 was released in August 2000.", "web", "https://sqlite.org/chronology.html", "[]", 100.0),
        ("SQLite was first released in 2000.", "conclusion", None, "[1]", 200.0),
        ("Prince prefers Vim.", "human", None, "[]", 300.0),
    ]
    for claim, kind, url, sources, created in rows:
        db.execute("INSERT INTO knowledge(claim, kind, source_url, confidence, basis, sources, tags, created) VALUES (?,?,?,?,?,?,?,?)",
                   (claim, kind, url, 0.4, "old", sources, "[]", created))
    db.execute("DELETE FROM knowledge WHERE id=2")  # a gap in the ids must survive too
    db.execute("INSERT INTO knowledge(claim, kind, source_url, confidence, basis, sources, tags, created) VALUES (?,?,?,?,?,?,?,?)",
               ("SQLite was first released in 2000.", "conclusion", None, 0.4, "old", "[1]", "[]", 200.0))
    db.commit()
    db.close()

    j = Journal(path)
    cols = {r["name"] for r in j._db.execute("PRAGMA table_info(knowledge)")}
    assert {"status", "verified_at", "superseded_by"} <= cols
    got = {k["id"]: k for k in j.knowledge_of_kind(("web", "conclusion", "human"))}
    assert sorted(got) == [1, 3, 4] and j.count("knowledge") == 3
    assert {k["status"] for k in got.values()} == {"ACTIVE"} and all(k["superseded_by"] is None for k in got.values())
    assert got[1]["verified_at"] == 100.0 and got[4]["verified_at"] == 200.0  # rests on a source: verified when stored
    assert got[3]["verified_at"] is None  # the human's word has no source to check
    assert got[3]["claim"] == "Prince prefers Vim." and got[4]["sources"] == [1]
    # the migration runs once: reopening neither fails nor backfills again
    j._db.execute("UPDATE knowledge SET verified_at=NULL WHERE id=1")
    j._db.close()
    j2 = Journal(path, recover=False)
    assert j2.knowledge(1)["verified_at"] is None and j2.count("knowledge") == 3
    # and the migrated file works with the new rules
    nid = j2.add_knowledge_sync("SQLite 3.0 shipped in 2004.", "web", source_url="https://sqlite.org/x")["id"]
    assert nid == 5 and j2.knowledge(nid)["status"] == "ACTIVE" and j2.knowledge(nid)["verified_at"] is not None


def test_a_reader_beside_an_owner_on_the_old_schema_reads_it_unmigrated(tmp_path, monkeypatch):
    from syrax import journal as journal_mod

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript(OLD_KNOWLEDGE)
    db.execute("INSERT INTO knowledge(claim, kind, confidence, basis, sources, tags, created) VALUES (?,?,?,?,?,?,?)",
               ("Prince prefers Vim.", "human", 1.0, "old", "[]", "[]", 1.0))
    db.commit()
    db.close()
    monkeypatch.setattr(journal_mod, "_owned_elsewhere", lambda p: True)  # the running SYRAX owns it
    j = Journal(path, recover=False)
    assert j.read_only
    assert [(k["claim"], k["status"]) for k in j.human_facts()] == [("Prince prefers Vim.", "ACTIVE")]
    assert [k["claim"] for k in j.knowledge_recent()] == ["Prince prefers Vim."]
    assert "status" not in {r["name"] for r in j._db.execute("PRAGMA table_info(knowledge)")}  # never migrated from here


def test_a_new_journal_has_the_columns_and_refuses_an_unknown_status(tmp_path):
    j = Journal(tmp_path / "j.db")
    kid = web(j, "SQLite is a C library.", "https://sqlite.org/about.html")
    with pytest.raises(sqlite3.IntegrityError):
        j._db.execute("UPDATE knowledge SET status='MAYBE' WHERE id=?", (kid,))


# ——— disputes are kept on the row ———


def test_a_contradiction_marks_both_rows_disputed_and_it_does_not_age_out(tmp_path):
    j, _, a, b = disputed_pair(tmp_path)
    assert j.knowledge(a)["status"] == j.knowledge(b)["status"] == "DISPUTED"
    ev = events(j, "knowledge.disputed")[-1]
    assert sorted(ev["knowledge_ids"]) == sorted([a, b]) and ev["why"]
    assert events(j, "knowledge.contradiction")[-1]["conflicts_with"] == [a]
    # 3000+ later events push the contradiction out of the window `know` used to recompute DISPUTED from
    with j._txn() as cur:
        for i in range(3100):
            j._insert_event(cur, time.time(), None, "test.filler", {"i": i})
    shown = know(j, "sqlite first released")
    for kid in (a, b):
        line = next(ln for ln in shown.splitlines() if ln.startswith(f"- id={kid} "))
        assert "(disputed)" in line
    assert shown.count("DISPUTED:") == 2 and "Do not state it as fact" in shown


def test_independent_evidence_settles_a_dispute_and_supersedes_the_loser(tmp_path):
    j, src, a, b = disputed_pair(tmp_path)
    # the same source again settles nothing
    out = learn(j, "SQLite was first released in August 2000.", src)
    assert "CONTRADICTS" in out and j.knowledge(a)["status"] == j.knowledge(b)["status"] == "DISPUTED"
    before = j.knowledge(a)["verified_at"]
    fresh = web(j, "The first SQLite release, version 1.0, came out in August 2000.", "https://example.org/b")
    out = learn(j, "SQLite was first released in August 2000.", fresh)
    assert "SETTLED" in out and f"SUPERSEDED by id={a}" in out
    win, lose = j.knowledge(a), j.knowledge(b)
    assert win["status"] == "ACTIVE" and win["verified_at"] > before
    assert lose["status"] == "SUPERSEDED" and lose["superseded_by"] == a
    ev = events(j, "knowledge.superseded")[-1]
    assert ev["knowledge_ids"] == [b] and ev["superseded_by"] == a and ev["evidence"] == [fresh] and ev["was"] == "DISPUTED"
    # readers: the loser is not retrieved, the winner is not marked
    shown = know(j, "sqlite first released")
    assert f"id={b} " not in shown and f"- id={a} " in shown and "(disputed)" not in shown
    assert b not in [k["id"] for k in j.knowledge_recent(50)] and b in [k["id"] for k in j.knowledge_recent(50, include_superseded=True)]
    # the loser is history: it is compared with nothing, and citing it is refused
    dup, conflicts = consolidate.compare("SQLite was first released in August 2004.", j)
    assert dup is None and [k["id"] for k in conflicts] == [a]
    assert "superseded by" in asyncio.run(LearnTool(journal=j).execute(claim="SQLite came out in August 2004.", sources=[b])).error


def test_weaker_independent_evidence_does_not_settle(tmp_path):
    j = Journal(tmp_path / "j.db")
    strong = j.add_knowledge_sync("SQLite 1.0 shipped in August 2004 per the release archive.", "local", source_url="file:///notes.txt")
    b = j.add_knowledge_sync("SQLite was first released in August 2004.", "conclusion", sources=[strong["id"]], confidence=0.9)["id"]
    src = web(j, "SQLite 1.0 was released in August 2000.", "https://example.org/a")
    learn(j, "SQLite was first released in August 2000.", src)
    a = j.knowledge_of_kind(("conclusion",))[-1]["id"]
    assert j.knowledge(a)["status"] == j.knowledge(b)["status"] == "DISPUTED"
    fresh = web(j, "The first SQLite release came out in August 2000.", "https://example.org/b")  # 0.4 < 0.9
    out = learn(j, "SQLite was first released in August 2000.", fresh)
    assert "SETTLED" not in out and "CONTRADICTS" in out
    assert j.knowledge(a)["status"] == j.knowledge(b)["status"] == "DISPUTED"


def test_a_first_contradiction_is_disputed_even_with_fresh_evidence(tmp_path):
    j = Journal(tmp_path / "j.db")
    src = web(j, "SQLite 1.0 was released in August 2004.", "https://example.org/a")
    b = j.add_knowledge_sync("SQLite was first released in August 2004.", "conclusion", sources=[src])["id"]
    fresh = web(j, "SQLite 1.0 was released in August 2000.", "https://example.org/b")
    out = learn(j, "SQLite was first released in August 2000.", fresh)
    assert "CONTRADICTS" in out and "SETTLED" not in out
    assert j.knowledge(b)["status"] == "DISPUTED"


# ——— the journal enforces the transitions ———


def test_superseded_is_final_and_kinds_do_not_mix(tmp_path):
    j, src, a, b = disputed_pair(tmp_path)
    with pytest.raises(JournalError, match="cannot supersede"):
        j.supersede_knowledge_sync([src], a, "a conclusion never replaces its web excerpt")
    j.supersede_knowledge_sync([b], a, "test")
    assert j.dispute_knowledge_sync([b], "again") == [] and j.knowledge(b)["status"] == "SUPERSEDED"
    with pytest.raises(JournalError, match="SUPERSEDED"):
        j.supersede_knowledge_sync([a], b, "the loser cannot come back as a winner")
    with pytest.raises(JournalError, match="SUPERSEDED"):
        j.update_knowledge_claim_sync(b, "rewritten")
    assert j.verify_knowledge_sync(b) is None and j.knowledge(b)["verified_at"] == j.knowledge(b)["created"]


def test_research_reconfirming_a_page_refreshes_verified_at(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    page = "SQLite write-ahead logging: with synchronous FULL each commit syncs the WAL, durable across power loss. " * 3
    monkeypatch.setattr(research, "ENGINES", [lambda q, n: [Source(url="http://a", title="A", snippet="wal", engine="fake")]])

    async def fetch(url):
        return page

    r = Researcher(j, fetcher=fetch)
    asyncio.run(r.research("sqlite synchronous FULL WAL commit", 1))
    k = j.knowledge_recent()[0]
    assert k["verified_at"] == k["created"]
    asyncio.run(r.research("sqlite synchronous FULL WAL commit", 1))
    assert j.count("knowledge") == 1 and j.knowledge(k["id"])["verified_at"] > k["created"]


# ——— memory: a correction keeps what it replaced ———


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")


def test_a_correction_keeps_the_old_text_as_a_superseded_row(store):
    store.remember("Prince prefers Vim.")
    fid = store.facts()[0]["id"]
    store.correct(fid, "Prince prefers VS Code.")
    j = get_journal()
    rows = {k["id"]: k for k in j.knowledge_of_kind(("human",))}
    old = [k for k in rows.values() if k["status"] == "SUPERSEDED"]
    assert len(old) == 1 and old[0]["claim"] == "Prince prefers Vim." and old[0]["superseded_by"] == int(fid)
    assert rows[int(fid)]["claim"] == "Prince prefers VS Code." and rows[int(fid)]["status"] == "ACTIVE"
    assert events(j, "knowledge.updated")[-1]["previous_id"] == old[0]["id"]
    # readers: the old version is no fact, is not recalled, retrieved or put in the prompt, and cannot be corrected
    assert [f["text"] for f in store.facts()] == ["Prince prefers VS Code."]
    assert store.recall("Vim") == [] and [k["id"] for k in j.knowledge_search("prefers Vim")] == [int(fid)]
    assert "Vim" not in store.prompt_block()
    with pytest.raises(CorrectRefused, match="no remembered fact"):
        store.correct(str(old[0]["id"]), "Prince prefers Emacs.")


def test_remember_overwrite_keeps_the_old_text_too(store):
    store.remember("Prince's favourite editor is Vim.", "preference")
    store.remember("Prince's favourite editor is VS Code.", "preference")
    old = [k for k in get_journal().knowledge_of_kind(("human",)) if k["status"] == "SUPERSEDED"]
    assert [k["claim"] for k in old] == ["Prince's favourite editor is Vim."]
    # the same text again is no new version
    store.remember("Prince's favourite editor is VS Code.", "preference")
    assert len([k for k in get_journal().knowledge_of_kind(("human",)) if k["status"] == "SUPERSEDED"]) == 1


def test_forgetting_a_fact_forgets_its_earlier_versions(store):
    store.remember("Prince prefers Vim.")
    fid = store.facts()[0]["id"]
    store.correct(fid, "Prince prefers VS Code.")
    store.correct(fid, "Prince prefers Zed.")
    j = get_journal()
    assert j.count("knowledge") == 3
    assert store.forget(fid) == ["Prince prefers Zed."]
    assert j.count("knowledge") == 0 and len(events(j, "knowledge.forgotten")[-1]["versions"]) == 2


def test_export_carries_status_and_the_superseded_versions(store, tmp_path):
    store.remember("Prince prefers Vim.")
    fid = store.facts()[0]["id"]
    store.correct(fid, "Prince prefers VS Code.")
    j = get_journal()
    src = web(j, "SQLite 1.0 was released in August 2000.", "https://example.org/a")
    out = store.export(tmp_path / "m.json")
    doc = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    assert out["count"] == 1 and doc["facts"][0]["status"] == "ACTIVE"
    assert [(f["text"], f["status"], f["superseded_by"]) for f in doc["superseded_facts"]] == [("Prince prefers Vim.", "SUPERSEDED", int(fid))]
    k = next(k for k in doc["knowledge"] if k["id"] == src)
    assert k["status"] == "ACTIVE" and k["verified_at"] is not None and k["superseded_by"] is None


def test_a_disputed_fact_is_marked_in_the_prompt_and_in_recall(store):
    store.remember("Prince lives in Dhaka.")
    fid = store.facts()[0]["id"]
    get_journal().dispute_knowledge_sync([int(fid)], "test: a stored row contradicts it")
    assert "- (disputed) Prince lives in Dhaka." in store.prompt_block()
    assert store.facts()[0]["status"] == "DISPUTED"
    assert "(disputed) Prince lives in Dhaka." in asyncio.run(RecallTool(store=store).execute("Dhaka"))
