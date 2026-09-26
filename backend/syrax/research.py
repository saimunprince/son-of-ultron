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
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence

import requests
from bs4 import BeautifulSoup
from pydantic import Field

from app.tool.base import BaseTool, ToolResult
from app.tool.web_search import WebContentFetcher

from syrax.journal import Journal, JournalError, re_words

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
        stored = 0
        for src in sources:
            if not src.excerpts:
                continue
            row = await asyncio.to_thread(
                self.journal.add_knowledge_sync,
                claim=src.excerpts[0],
                kind="web",
                source_url=src.url,
                source_title=src.title[:200],
                excerpt="\n…\n".join(src.excerpts),
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
            "fetched": fetched,
            "search_failures": failures,
            "ms": int((time.time() - started) * 1000),
        }
        await self.journal.record(
            "research.completed",
            {"question": question, "sources": len(sources), "fetched": fetched, "stored": stored, "failures": failures, "ms": report["ms"]},
            task_id=task_id,
        )
        return report


def render_report(report: dict) -> str:
    lines = [f"RESEARCH: {report['question']}"]
    if not report["sources"]:
        lines.append("No sources found." + (f" Search failures: {'; '.join(report['search_failures'])}" if report["search_failures"] else ""))
        lines.append("State: UNKNOWN. Do not answer as if you had evidence.")
        return "\n".join(lines)
    for i, s in enumerate(report["sources"], 1):
        lines.append(f"\n[{i}] knowledge_id={s['knowledge_id']} · {s['title'] or 'untitled'} · {s['url']} · {'page fetched' if s['fetched'] else 'snippet only'} · agreeing sources: {s['agreeing']}")
        for ex in s["excerpts"]:
            lines.append(f"    \"{ex}\"")
    lines.append(f"\nStored {report['stored']} knowledge entries with provenance ({report['ms']} ms).")
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
        },
        "required": ["question"],
    }
    researcher: Optional[Any] = Field(default=None, exclude=True)

    async def execute(self, question: str, max_sources: int = 4) -> ToolResult:
        if self.researcher is None:
            return ToolResult(error="research engine unavailable (core not started)")
        try:
            report = await self.researcher.research(question, max_sources)
        except ValueError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            log.exception("research failed")
            return ToolResult(error=f"research failed: {e.__class__.__name__}: {str(e)[:200]}")
        return ToolResult(output=render_report(report))


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
        lines = [f"KNOWN ({len(rows)} entries):"]
        for k in rows:
            src = k["source_url"] or (f"sources {k['sources']}" if k["sources"] else "no url")
            lines.append(f"- id={k['id']} [{k['kind']} · confidence {k['confidence']:.2f}] {k['claim'][:300]}\n    source: {src}")
        return ToolResult(output="\n".join(lines))


class LearnTool(BaseTool):
    name: str = "learn"
    description: str = (
        "Store a conclusion you verified, citing the knowledge_ids (from `research`/`know`) or a "
        "URL it rests on. Its confidence can never exceed the confidence of the cited sources; "
        "uncited conclusions are refused."
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
        ids = [int(s) for s in (sources or []) if isinstance(s, int) or (isinstance(s, str) and s.isdigit())]
        urls = [s for s in (sources or []) if isinstance(s, str) and s.startswith("http")]
        if not ids and not urls:
            return ToolResult(error="learn refused: cite at least one knowledge_id or URL")
        cited = [self.journal.knowledge(i) for i in ids]
        missing = [i for i, k in zip(ids, cited) if k is None]
        if missing:
            return ToolResult(error=f"learn refused: unknown knowledge_id(s) {missing}")
        cap = max([k["confidence"] for k in cited if k] + ([0.4] if urls else []))
        want = cap if confidence is None else min(float(confidence), cap)
        try:
            row = await asyncio.to_thread(
                self.journal.add_knowledge_sync,
                claim=claim, kind="conclusion", sources=ids + urls, source_url=urls[0] if urls else None,
                tags=list(tags or []) + sorted(set(keywords(claim)))[:6], confidence=want,
                task_id=self.task_id_provider() if self.task_id_provider else None,
                basis=f"conclusion resting on {len(ids)} stored source(s) and {len(urls)} url(s); capped at {cap:.2f}",
            )
        except JournalError as e:
            return ToolResult(error=f"learn refused: {e}")
        return ToolResult(output=f"Learned id={row['id']} with confidence {row['confidence']:.2f} (cap {cap:.2f}).")
