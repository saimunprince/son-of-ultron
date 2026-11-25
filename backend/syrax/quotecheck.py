"""Quote and citation check for a researched answer (idea from Mark-LVII JARVIS; own code).

`research` stores verbatim excerpts of the pages it read, but the brain writes the report, and nothing held that
report to them: a quotation could be paraphrased, invented, or pinned on the wrong page. `verify` holds it to them,
in code, after the brain's text is returned and before it reaches the human:

  - every quotation (straight or curly quotes, 4+ words) that cites a source ([n], the source's URL, or its
    knowledge_id) is looked up in that source's text: exact (word for word), partial (same words once case,
    whitespace and punctuation are normalised, or a close in-order match of most of its words) or missing;
    a missing quotation is removed and says so, never left standing as sourced;
  - a citation number that points to no source becomes [?] and is counted;
  - a finding whose citations all point to sources whose page was never opened (search snippet only) is marked;
  - a short footer line says what was checked.

Pure functions: no network, no journal. `research.Researcher.verify_answer` feeds it the task's sources and
journals the result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional, Sequence

MIN_QUOTE_WORDS = 4  # shorter quoted strings are names and terms ("WAL", "synchronous=FULL"), not findings
FUZZY_SHARE = 0.85  # share of the quote's words found in order in the source for a partial match
FUZZY_SPREAD = 1.5  # ... within a stretch of the source at most this many times the quote's length

QUOTE = re.compile(r"\"([^\"\n]+)\"|“([^”\n]+)”")
CITATION = re.compile(r"\[(\d{1,3})\]|\bknowledge_id\s*[=:#]\s*(\d+)|(https?://[^\s<>\"\]\)]+)", re.I)
ELLIPSIS = re.compile(r"\s*(?:…|\.\.\.)\s*")
REMOVED = "[quote removed: not found in the cited source]"
SNIPPET_MARK = " (snippet only: page not opened)"


@dataclass
class Checked:
    exact: int = 0
    partial: int = 0
    missing: int = 0
    broken: int = 0
    snippet_only: int = 0
    unchecked: int = 0  # quotations citing only a URL no research call read: not ours to judge
    details: List[dict] = field(default_factory=list)

    @property
    def quotes(self) -> int:
        return self.exact + self.partial + self.missing

    def footer(self) -> str:
        if not (self.quotes or self.broken or self.snippet_only):
            return ""
        parts = [f"{self.exact} exact, {self.partial} partial, {self.missing} not found and removed" if self.quotes else "none"]
        tail = []
        if self.broken:
            tail.append(f"{self.broken} broken citation{'s' if self.broken != 1 else ''}")
        if self.snippet_only:
            tail.append(f"{self.snippet_only} finding{'s rest' if self.snippet_only != 1 else ' rests'} on a search snippet only")
        return "Quotes checked: " + "; ".join(parts + tail) + "."

    def payload(self) -> dict:
        return {"exact": self.exact, "partial": self.partial, "missing": self.missing, "broken_citations": self.broken,
                "snippet_only": self.snippet_only, "unchecked": self.unchecked, "details": self.details[:20]}


def normalise(text: str) -> str:
    """Lower case, punctuation gone, whitespace collapsed; curly quotes and dashes count as punctuation."""
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def _fuzzy(quote_words: List[str], text_words: List[str]) -> bool:
    if not quote_words or not text_words:
        return False
    blocks = [b for b in SequenceMatcher(None, quote_words, text_words, autojunk=False).get_matching_blocks() if b.size]
    if not blocks:
        return False
    # the longest in-order run of blocks that sits in a compact stretch of the source
    limit = FUZZY_SPREAD * len(quote_words) + 3
    best = 0
    for i in range(len(blocks)):
        got = 0
        for b in blocks[i:]:
            if b.b + b.size - blocks[i].b > limit:
                break
            got += b.size
        best = max(best, got)
    return best / len(quote_words) >= FUZZY_SHARE


def match(quote: str, text: str) -> str:
    """'exact', 'partial' or 'missing': how `quote` stands against a source's `text`. A quotation with an ellipsis
    is checked piece by piece, and it is only as good as its worst piece."""
    pieces = [p for p in ELLIPSIS.split(quote.strip()) if normalise(p)]
    if not pieces or not text:
        return "missing"
    rank = {"exact": 2, "partial": 1, "missing": 0}
    worst = "exact"
    norm_text = None
    for piece in pieces:
        if piece in text:
            continue
        if norm_text is None:
            norm_text = normalise(text)
        np = normalise(piece)
        if f" {np} " in f" {norm_text} " or _fuzzy(np.split(), norm_text.split()):
            got = "partial"
        else:
            return "missing"
        worst = min(worst, got, key=rank.get)
    return worst


def _url_key(url: str) -> str:
    u = (url or "").strip().rstrip(".,;:!?)'\"").lower()
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u.rstrip("/")


@dataclass
class _Cite:
    start: int
    end: int
    source: Optional[dict]  # the source it resolves to
    broken: bool = False  # a number that points to no source


def _citations(line: str, sources: Sequence[dict]) -> List[_Cite]:
    by_n = {int(s["n"]): s for s in sources if s.get("n") is not None}
    by_url = {_url_key(s["url"]): s for s in sources if s.get("url")}
    by_kid = {int(s["knowledge_id"]): s for s in sources if s.get("knowledge_id") is not None}
    out = []
    for m in CITATION.finditer(line):
        if m.group(1):
            src = by_n.get(int(m.group(1)))
            out.append(_Cite(m.start(), m.end(), src, broken=src is None))
        elif m.group(2):
            out.append(_Cite(m.start(), m.end(), by_kid.get(int(m.group(2)))))
        else:
            out.append(_Cite(m.start(), m.end(), by_url.get(_url_key(m.group(3)))))
    return out


def _cites_for(qs: int, qe: int, next_q: int, prev_q: int, cites: List[_Cite]) -> List[_Cite]:
    """The citations a quotation rests on: those after it up to the next quotation, else those before it back to the
    previous one."""
    after = [c for c in cites if qe <= c.start < next_q]
    return after or [c for c in cites if prev_q <= c.start and c.end <= qs]


def verify(text: str, sources: Sequence[dict]) -> tuple:
    """Check `text` (the brain's answer) against `sources` (dicts with n, url, text, fetched, knowledge_id).
    Returns (new text with the footer line, Checked). With no sources the text comes back unchanged."""
    result = Checked()
    if not text or not sources:
        return text, result
    lines = text.split("\n")
    for li, line in enumerate(lines):
        cites = _citations(line, sources)
        quotes = [m for m in QUOTE.finditer(line) if len((m.group(1) or m.group(2) or "").split()) >= MIN_QUOTE_WORDS]
        if not cites:
            continue
        edits = []  # (start, end, replacement), applied from the end of the line
        for qi, m in enumerate(quotes):
            next_q = quotes[qi + 1].start() if qi + 1 < len(quotes) else len(line)
            prev_q = quotes[qi - 1].end() if qi else 0
            mine = _cites_for(m.start(), m.end(), next_q, prev_q, cites)
            if not mine:
                continue  # a quotation with no citation does not claim a source
            quote = m.group(1) or m.group(2)
            known = [c.source for c in mine if c.source is not None]
            if not known and not any(c.broken for c in mine):
                result.unchecked += 1
                continue
            rank = {"exact": 2, "partial": 1, "missing": 0}
            best = max((match(quote, s.get("text") or "") for s in known), key=rank.get, default="missing")
            setattr(result, best, getattr(result, best) + 1)
            result.details.append({"quote": quote[:200], "result": best, "sources": [s.get("url") for s in known]})
            if best == "missing":
                edits.append((m.start(), m.end(), REMOVED))
        for c in cites:
            if c.broken:
                result.broken += 1
                edits.append((c.start, c.end, "[?]"))
        resolved = [c for c in cites if c.source is not None]
        if resolved and all(not c.source.get("fetched") for c in resolved) and SNIPPET_MARK.strip() not in line:
            result.snippet_only += 1
            last = resolved[-1]
            edits.append((last.end, last.end, SNIPPET_MARK))
        for s, e, rep in sorted(edits, key=lambda x: (x[0], x[1]), reverse=True):
            line = line[:s] + rep + line[e:]
        lines[li] = line
    out = "\n".join(lines)
    footer = result.footer()
    if footer:
        out = out.rstrip() + "\n\n" + footer
    return out, result
