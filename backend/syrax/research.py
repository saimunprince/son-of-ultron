"""SYRAX research engine: search, collect evidence, store knowledge with provenance.

    question
      → search (ddgs, then DuckDuckGo lite HTML as a dependency-free fallback)
      → fetch each page (upstream WebContentFetcher: requests + BeautifulSoup)
      → extract the passages that overlap the question (keyword windows)
      → store one knowledge row per source (kind=web, confidence from the
        number of sources that agree on the same key terms)
      → return sources + excerpts + knowledge ids to the model

The tool does no synthesis and never invents a claim: every stored row is a
verbatim excerpt with its URL. Synthesis is the model's job; when it reaches a
conclusion it can `learn` it, and that conclusion's confidence can never
exceed the confidence of the sources it cites.

Tools: research {question, max_sources}, know {query}, learn {claim, sources, confidence?}.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence

import requests
from bs4 import BeautifulSoup
from pydantic import Field

from app.tool.base import BaseTool, ToolResult
from app.tool.web_search import WebContentFetcher

from syrax.journal import Journal, JournalError, re_words
from syrax.redact import UNTRUSTED_WEB

log = logging.getLogger("syrax.research")

STOP = set(
    "the a an and or of to in on for with is are was were be by at as it its this that from how what why "
    "when which who does do did can could should would about into than then there their they them we you "
    "your our not no yes if but so such via per use used using".split()
)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
WINDOW_CHARS = 420
MAX_EXCERPTS_PER_SOURCE = 2
MAX_SOURCES = 6


@dataclass
class Source:
    url: str
    title: str = ""
    snippet: str = ""
    content: Optional[str] = None
    excerpts: List[str] = field(default_factory=list)
    terms: set = field(default_factory=set)
    knowledge_id: Optional[int] = None
    engine: str = ""


def keywords(text: str) -> List[str]:
    return [w for w in re_words(text) if len(w) > 2 and w not in STOP]


# ——— search engines ———


def search_ddgs(query: str, max_results: int) -> List[Source]:
    from ddgs import DDGS  # imported lazily: optional dependency

    out = []
    for item in DDGS().text(query, max_results=max_results):
        if isinstance(item, dict) and item.get("href"):
            out.append(Source(url=item["href"], title=(item.get("title") or "")[:160], snippet=item.get("body") or "", engine="ddgs"))
    return out


def search_ddg_lite(query: str, max_results: int) -> List[Source]:
    r = requests.post("https://lite.duckduckgo.com/lite/", data={"q": query}, headers=UA, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    links = soup.select("a.result-link")
    snippets = [td.get_text(" ", strip=True) for td in soup.select("td.result-snippet")]
    for i, a in enumerate(links[:max_results]):
        href = a.get("href") or ""
        if href.startswith("http"):
            out.append(Source(url=href, title=a.get_text(strip=True)[:160], snippet=snippets[i] if i < len(snippets) else "", engine="ddg-lite"))
    return out


ENGINES: List[Callable[[str, int], List[Source]]] = [search_ddgs, search_ddg_lite]


async def search(query: str, max_results: int) -> tuple[List[Source], List[str]]:
    """Try engines in order in a worker thread. Returns (sources, failures)."""
    failures: List[str] = []
    for engine in ENGINES:
        try:
            found = await asyncio.to_thread(engine, query, max_results)
        except Exception as e:
            failures.append(f"{engine.__name__}: {e.__class__.__name__}: {str(e)[:120]}")
            continue
        if found:
            return found, failures
        failures.append(f"{engine.__name__}: no results")
    return [], failures


# ——— evidence extraction ———


def extract_excerpts(text: str, question: str, limit: int = MAX_EXCERPTS_PER_SOURCE) -> List[str]:
    """Windows of the page text with the highest question-keyword overlap."""
    if not text:
        return []
    kws = set(keywords(question))
    if not kws:
        return [text[:WINDOW_CHARS]]
    windows = [text[i : i + WINDOW_CHARS] for i in range(0, max(1, len(text) - WINDOW_CHARS // 2), WINDOW_CHARS // 2)]
    scored = []
    for w in windows:
        ws = set(re_words(w))
        hits = len(kws & ws)
        if hits:
            scored.append((hits, w.strip()))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: List[str] = []
    for _, w in scored:
        if all(w[:80] != o[:80] for o in out):
            out.append(w)
        if len(out) >= limit:
            break
    return out


def agreement(sources: Sequence[Source]) -> dict:
    """How many sources share each source's key terms (>=3 shared non-stop
    terms with another source counts as agreeing on the same points)."""
    counts = {}
    for i, a in enumerate(sources):
        n = 1
        for j, b in enumerate(sources):
            if i != j and len(a.terms & b.terms) >= 3:
                n += 1
        counts[a.url] = n
    return counts


# ——— the engine ———


class Researcher:
    def __init__(self, journal: Journal, task_id_provider: Optional[Callable[[], Optional[str]]] = None,
                 fetcher: Optional[Callable[[str], Any]] = None):
        self.journal = journal
        self.task_id_provider = task_id_provider or (lambda: None)
        self.fetch = fetcher or WebContentFetcher.fetch_content

    async def research(self, question: str, max_sources: int = 4) -> dict:
        question = (question or "").strip()
        if not question:
            raise ValueError("question required")
        max_sources = max(1, min(int(max_sources or 4), MAX_SOURCES))
        started = time.time()
        task_id = self.task_id_provider()
        await self.journal.record("research.started", {"question": question, "max_sources": max_sources}, task_id=task_id)
        sources, failures = await search(question, max_sources)
        fetched = 0
        for src in sources:
            try:
                src.content = await self.fetch(src.url)
            except Exception as e:  # a dead page is evidence of nothing
                log.info("fetch failed %s: %s", src.url, e)
                src.content = None
            if src.content:
                fetched += 1
            base = src.content or src.snippet
            src.excerpts = extract_excerpts(base, question) if base else []
            src.terms = set(keywords(" ".join(src.excerpts) or src.snippet))
        agree = agreement(sources)
        tags = sorted(set(keywords(question)))[:8]
        stored = reinforced = 0
        for src in sources:
            if not src.excerpts:
                continue
            excerpt = "\n…\n".join(src.excerpts)
            # the same page excerpt is reinforced, not stored again (live 2026-10-26: one excerpt stored 24 times)
            known = await asyncio.to_thread(self.journal.web_knowledge_like, src.url, excerpt)
            if known is not None:
                await self.journal.record("knowledge.reinforced", {
                    "knowledge_id": known["id"], "kind": "web", "claim": known["claim"][:300], "tags": known.get("tags") or [],
                    "question": question, "source_url": src.url, "agreeing_sources": agree.get(src.url, 1)}, task_id=task_id)
                # the page still says it: the row is verified again (verified_at), its status untouched
                await asyncio.to_thread(self.journal.verify_knowledge_sync, known["id"], task_id=task_id)
                src.knowledge_id = known["id"]
                reinforced += 1
                continue
            row = await asyncio.to_thread(
                self.journal.add_knowledge_sync,
                claim=src.excerpts[0],
                kind="web",
                source_url=src.url,
                source_title=src.title[:200],
                excerpt=excerpt,
                tags=tags,
                question=question,
                task_id=task_id,
                agreeing_sources=agree.get(src.url, 1),
                basis=f"web excerpt via {src.engine}; {agree.get(src.url, 1)} source(s) share its key terms; page {'fetched' if src.content else 'NOT fetched (snippet only)'}",
            )
            src.knowledge_id = row["id"]
            stored += 1
        report = {
            "question": question,
            "sources": [
                {"knowledge_id": s.knowledge_id, "url": s.url, "title": s.title, "fetched": bool(s.content), "agreeing": agree.get(s.url, 1), "excerpts": s.excerpts}
                for s in sources
            ],
            "stored": stored,
            "reinforced": reinforced,
            "fetched": fetched,
            "search_failures": failures,
            "ms": int((time.time() - started) * 1000),
        }
        await self.journal.record(
            "research.completed",
            {"question": question, "sources": len(sources), "fetched": fetched, "stored": stored, "reinforced": reinforced,
             "failures": failures, "ms": report["ms"]},
            task_id=task_id,
        )
        return report


def render_report(report: dict) -> str:
    # the first line says what the rest is: excerpts from pages, data for the model, never instructions (audit 2026-10-25)
    lines = [UNTRUSTED_WEB, f"RESEARCH: {report['question']}"]
    if not report["sources"]:
        lines.append("No sources found." + (f" Search failures: {'; '.join(report['search_failures'])}" if report["search_failures"] else ""))
        lines.append("State: UNKNOWN. Do not answer as if you had evidence.")
        return "\n".join(lines)
    for i, s in enumerate(report["sources"], 1):
        lines.append(f"\n[{i}] knowledge_id={s['knowledge_id']} · {s['title'] or 'untitled'} · {s['url']} · {'page fetched' if s['fetched'] else 'snippet only'} · agreeing sources: {s['agreeing']}")
        for ex in s["excerpts"]:
            lines.append(f"    \"{ex}\"")
    again = report.get("reinforced") or 0
    lines.append(f"\nStored {report['stored']} knowledge entries with provenance"
                 + (f"; {again} already known (same page and excerpt), reinforced under the same knowledge_id" if again else "")
                 + f" ({report['ms']} ms).")
    lines.append("These are excerpts, not conclusions. Compare them, note disagreement, and cite knowledge_ids. "
                 "If you reach a verified conclusion, store it with `learn` citing those ids.")
    return "\n".join(lines)


class ResearchTool(BaseTool):
    name: str = "research"
    description: str = (
        "Research a question on the web: searches, fetches the pages, extracts the relevant "
        "passages and stores them as knowledge with source URLs and a confidence derived from "
        "how many sources agree. Returns sources, excerpts and knowledge_ids. Use it whenever a "
        "task needs facts you do not have; check `know` first."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "What you need to find out, as a precise question."},
            "max_sources": {"type": "integer", "description": "How many sources to read (1-6, default 4)."},
            "force": {"type": "boolean", "description": "Search the web even when stored knowledge seems to answer it."},
        },
        "required": ["question"],
    }
    researcher: Optional[Any] = Field(default=None, exclude=True)

    async def execute(self, question: str, max_sources: int = 4, force: bool = False) -> ToolResult:
        if self.researcher is None:
            return ToolResult(error="research engine unavailable (core not started)")
        journal = getattr(self.researcher, "journal", None)
        if not force and journal is not None:
            known = await asyncio.to_thread(already_known, journal, question)
            if known:
                lines = [f"ALREADY KNOWN ({len(known)} fresh, sourced entries answer this; no web search was made). "
                         "If they do not answer the question, call research again with force=true."]
                lines += [f"- id={k['id']} [confidence {k['confidence']:.2f}] {k['claim'][:300]}\n    source: {k['source_url'] or k['sources']}"
                          for k in known]
                return ToolResult(output="\n".join(lines))
        try:
            report = await self.researcher.research(question, max_sources)
        except ValueError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            log.exception("research failed")
            return ToolResult(error=f"research failed: {e.__class__.__name__}: {str(e)[:200]}")
        return ToolResult(output=render_report(report))


STALE_DAYS = int(os.getenv("SYRAX_STALE_DAYS", "90"))  # web knowledge older than this is re-researched before use


VOI_MIN_ROWS, VOI_MIN_CONFIDENCE, VOI_OVERLAP = 2, 0.6, 0.6


def already_known(journal: Any, question: str) -> List[dict]:
    """Stored knowledge that already answers `question` well enough to skip a web search (EVOLUTION_PLAN direction 144
    value of information): at least VOI_MIN_ROWS ACTIVE rows, not stale, confidence VOI_MIN_CONFIDENCE or more, each
    sharing VOI_OVERLAP of the question's content words. Otherwise [] and the research goes ahead."""
    words = content_words(question)
    if len(words) < 2:
        return []
    good = []
    for k in journal.knowledge_search(question):
        if k.get("status", "ACTIVE") != "ACTIVE" or k["confidence"] < VOI_MIN_CONFIDENCE:
            continue
        age = knowledge_age_days(k)
        if age is not None and age > STALE_DAYS:
            continue
        if len(words & content_words(" ".join([k["claim"], k.get("question") or ""]))) / len(words) >= VOI_OVERLAP:
            good.append(k)
    return good if len(good) >= VOI_MIN_ROWS else []


def knowledge_age_days(row: dict, now: Optional[float] = None) -> Optional[int]:
    """Days since the row was last verified (verified_at), or stored when it never was; None when unknown."""
    t = row.get("verified_at") or row.get("created")
    try:
        return max(0, int(((now or time.time()) - float(t)) // 86400)) if t else None
    except (TypeError, ValueError):
        return None


class KnowTool(BaseTool):
    name: str = "know"
    description: str = (
        "Search what SYRAX already knows (stored knowledge with sources and confidence). "
        "Use before researching. Returns matching entries with ids, confidence and source URLs."
    )
    parameters: dict = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Keywords or a question."}},
        "required": ["query"],
    }
    journal: Optional[Any] = Field(default=None, exclude=True)

    async def execute(self, query: str) -> ToolResult:
        if self.journal is None:
            return ToolResult(error="knowledge store unavailable")
        rows = await asyncio.to_thread(self.journal.knowledge_search, query)
        if not rows:
            return ToolResult(output="Nothing stored about that yet. Use `research` to find out.")
        # DISPUTED is the row's own state (audit 2026-10-27: it was recomputed from the last 3000 events and aged
        # out); the events only name the other side when they still hold it. SUPERSEDED rows are not retrieved.
        partners: dict = {}
        if any(k.get("status") == "DISPUTED" for k in rows):
            for e in await asyncio.to_thread(self.journal.recent_events, 3000):
                if e["type"] == "knowledge.contradiction":
                    ids = [e["payload"].get("knowledge_id"), *(e["payload"].get("conflicts_with") or [])]
                    for x in ids:
                        partners.setdefault(x, set()).update(i for i in ids if i != x)
        lines = [f"KNOWN ({len(rows)} entries):"]
        for k in rows:
            src = k["source_url"] or (f"sources {k['sources']}" if k["sources"] else "no url")
            mark, warn = "", ""
            if k.get("status") == "DISPUTED":
                mark = " (disputed)"
                warn = ("\n    DISPUTED: " + (f"contradicts id(s) {sorted(partners[k['id']])}" if partners.get(k["id"]) else "another stored row contradicts it")
                        + ". Do not state it as fact until fresh research settles it.")
            age = knowledge_age_days(k)
            if k.get("kind") == "web" and age is not None and age > STALE_DAYS and k.get("status") != "DISPUTED":
                # mission 2026-10-28: an external fact ages; it is re-checked before it is stated as current
                mark = " (stale)"
                warn = (f"\n    STALE: last checked {age} days ago. Re-research it before stating it as current.")
            checked = "" if age is None else f" · checked {age} d ago"
            lines.append(f"- id={k['id']} [{k['kind']} · confidence {k['confidence']:.2f}{checked}]{mark} {k['claim'][:300]}\n    source: {src}{warn}")
        # one hop along a shared subject or object (journal.knowledge_links, wave 4): related facts the words missed
        related = await asyncio.to_thread(self.journal.linked_knowledge, [k["id"] for k in rows])
        if related:
            lines.append(f"RELATED ({len(related)}, linked by a shared name):")
            lines += [f"- id={k['id']} [{k['kind']} · confidence {k['confidence']:.2f}] {k['claim'][:200]}" for k in related]
        return ToolResult(output="\n".join(lines))


# A cited source as `research` ("knowledge_id=536") or `know` ("id=536") prints it, or a bare number.
_KNOWLEDGE_REF = re.compile(r"^(?:knowledge_id|id)?\s*[=:#]?\s*(\d+)$", re.I)

# Memory truth (2026-10-25 audit): a cited row must support the claim, not merely exist. Support is textual: the
# row's claim or excerpt shares SUPPORT_WORDS content words (lower-cased, no stopwords, 4+ letters) with the claim,
# or a number of two or more digits (a year, a version, a figure). A row that shares nothing is refused; one that
# shares a word or two is weak support (test_consolidate cites an SQLite row for a Python release): the conclusion
# is stored at half the cap and says so.
SUPPORT_WORDS = 3
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def content_words(text: str) -> set:
    return {w for w in re_words(text) if len(w) >= 4 and w not in STOP}


def support(claim: str, row: dict) -> int:
    """How far the cited knowledge row's text supports the claim: the shared content words, SUPPORT_WORDS when a
    number is shared (full support), 0 when nothing is."""
    text = " ".join(str(row.get(k) or "") for k in ("claim", "excerpt"))
    numbers = lambda s: {n for n in _NUMBER.findall(s or "") if len(n) >= 2}  # noqa: E731
    if numbers(claim) & numbers(text):
        return SUPPORT_WORDS
    return min(SUPPORT_WORDS, len(content_words(claim) & content_words(text)))


class LearnTool(BaseTool):
    name: str = "learn"
    description: str = (
        "Store a conclusion you verified, citing the knowledge_ids (from `research`/`know`) or a "
        "URL it rests on. Its confidence can never exceed the confidence of the cited sources; "
        "uncited conclusions are refused, and so is a cited row whose text does not support the claim."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "claim": {"type": "string", "description": "One precise sentence."},
            "sources": {"type": "array", "items": {"type": ["integer", "string"]}, "description": "knowledge_ids and/or URLs this rests on."},
            "confidence": {"type": "number", "description": "Optional 0-1; will be capped by the evidence."},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["claim", "sources"],
    }
    journal: Optional[Any] = Field(default=None, exclude=True)
    task_id_provider: Optional[Callable[[], Optional[str]]] = Field(default=None, exclude=True)

    async def execute(self, claim: str, sources: list, confidence: Optional[float] = None, tags: Optional[list] = None) -> ToolResult:
        if self.journal is None:
            return ToolResult(error="knowledge store unavailable")
        # 2026-10-19 and 2026-10-17: "knowledge_id=536", as research prints it, was refused as no source at all.
        ids = [int(m.group(1)) for s in (sources or []) if isinstance(s, (int, str))
               for m in [_KNOWLEDGE_REF.match(str(s).strip())] if m]
        urls = [s for s in (sources or []) if isinstance(s, str) and s.startswith("http")]
        if not ids and not urls:
            return ToolResult(error="learn refused: cite at least one knowledge_id or URL")
        cited = [self.journal.knowledge(i) for i in ids]
        missing = [i for i, k in zip(ids, cited) if k is None]
        if missing:
            return ToolResult(error=f"learn refused: unknown knowledge_id(s) {missing}")
        replaced = [k for k in cited if k.get("status") == "SUPERSEDED"]
        if replaced:  # history, not evidence (audit 2026-10-27, item 4)
            return ToolResult(error="learn refused: " + "; ".join(f"knowledge_id {k['id']} was superseded by {k['superseded_by']}" for k in replaced)
                                    + ": cite the current rows or fresh research")
        strength = {i: support(claim, k) for i, k in zip(ids, cited)}
        unsupported = [i for i, s in strength.items() if s == 0]
        if unsupported:  # the rows exist but say nothing about the claim: nothing is stored
            return ToolResult(error=f"learn refused: knowledge_id {', '.join(map(str, unsupported))} "
                                    f"{'does' if len(unsupported) == 1 else 'do'} not support the claim: cite the rows whose text does")
        weak = [i for i, s in strength.items() if s < SUPPORT_WORDS]
        cap = max([k["confidence"] for k in cited if k] + ([0.4] if urls else []))
        if weak:
            cap = round(cap / 2, 2)
        want = cap if confidence is None else min(float(confidence), cap)
        from syrax import consolidate

        tid = self.task_id_provider() if self.task_id_provider else None
        duplicate, conflicts = await asyncio.to_thread(consolidate.compare, claim, self.journal)
        full = {i for i, s in strength.items() if s >= SUPPORT_WORDS}
        fresh = consolidate.independent(cited, full, ([duplicate] if duplicate else []) + conflicts)
        settled = consolidate.settles(duplicate, conflicts, fresh)
        if duplicate is not None:  # Phase 5: reinforce what is known instead of storing it again
            await asyncio.to_thread(self.journal.record_sync, "knowledge.reinforced",
                                    {"knowledge_id": duplicate["id"], "claim": claim[:300], "tags": duplicate.get("tags") or []}, task_id=tid)
            out = (f"Already known as id={duplicate['id']} (confidence {duplicate['confidence']:.2f}): "
                   f"{duplicate['claim'][:200]} - reinforced, not stored again.")
            if settled:
                out += await self._settle(duplicate["id"], conflicts, fresh, tid)
            elif conflicts:  # still a duplicate, and the dispute stays on record against the row it duplicates
                await self._dispute(duplicate, claim, conflicts, tid)
                out += (" It CONTRADICTS " + "; ".join(f"id={k['id']}: {k['claim'][:160]}" for k in conflicts[:3])
                        + ". Do not rely on either until fresh research settles which is right.")
            elif fresh:  # confirmed again by a source it did not rest on: verified now, and a dispute with nothing left is over
                was = duplicate.get("status")
                await asyncio.to_thread(self.journal.verify_knowledge_sync, duplicate["id"], "confirmed by independent evidence",
                                        [k["id"] for k in fresh], True, tid)
                if was == "DISPUTED":
                    out += (f" It was DISPUTED; knowledge_id {', '.join(str(k['id']) for k in fresh)} confirms it and nothing "
                            "stored contradicts it now: ACTIVE again.")
            return ToolResult(output=out)
        try:
            row = await asyncio.to_thread(
                self.journal.add_knowledge_sync,
                claim=claim, kind="conclusion", sources=ids + urls, source_url=urls[0] if urls else None,
                tags=list(tags or []) + sorted(set(keywords(claim)))[:6], confidence=want,
                task_id=self.task_id_provider() if self.task_id_provider else None,
                basis=f"conclusion resting on {len(ids)} stored source(s) and {len(urls)} url(s); capped at {cap:.2f}"
                      + (f"; weak support from knowledge_id {', '.join(map(str, weak))} (under {SUPPORT_WORDS} shared content words), cap halved" if weak else ""),
            )
        except JournalError as e:
            return ToolResult(error=f"learn refused: {e}")
        out = f"Learned id={row['id']} with confidence {row['confidence']:.2f} (cap {cap:.2f})."
        if weak:
            out += (f" Weak support: knowledge_id {', '.join(map(str, weak))} shares under {SUPPORT_WORDS} content words with the claim, "
                    "so the cap was halved; cite rows whose text states it for full weight.")
        if settled:
            out += await self._settle(row["id"], conflicts, fresh, tid)
        elif conflicts:
            await self._dispute(row, claim, conflicts, tid)
            out += (" It CONTRADICTS " + "; ".join(f"id={k['id']}: {k['claim'][:160]}" for k in conflicts[:3])
                    + ". Do not rely on either until fresh research settles which is right.")
        return ToolResult(output=out)

    async def _dispute(self, row: dict, claim: str, conflicts: List[dict], tid: Optional[str]) -> None:
        """Journal the contradiction and mark every row in it DISPUTED, in one transaction."""
        await asyncio.to_thread(
            self.journal.dispute_knowledge_sync, [row["id"], *(k["id"] for k in conflicts)],
            f"id={row['id']} and id(s) {[k['id'] for k in conflicts]} state different figures about the same thing", tid,
            {"knowledge_id": row["id"], "claim": claim[:300], "conflicts_with": [k["id"] for k in conflicts],
             "their_claims": [k["claim"][:200] for k in conflicts[:3]], "tags": row.get("tags") or []})

    async def _settle(self, winner: int, conflicts: List[dict], fresh: List[dict], tid: Optional[str]) -> str:
        """Independent evidence settles the dispute for `winner`: the rows it contradicts are SUPERSEDED by it."""
        await asyncio.to_thread(
            self.journal.supersede_knowledge_sync, [k["id"] for k in conflicts], winner,
            f"independent evidence {[k['id'] for k in fresh]} (confidence {max(k['confidence'] for k in fresh):.2f}) supports id={winner}",
            [k["id"] for k in fresh], tid)
        return (f" SETTLED: knowledge_id {', '.join(str(k['id']) for k in fresh)} (independent of the disputed rows) supports id={winner}; "
                + "; ".join(f"id={k['id']} ({k['claim'][:120]})" for k in conflicts[:3]) + f" SUPERSEDED by id={winner}.")
