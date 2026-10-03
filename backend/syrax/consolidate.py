"""Phase 5: knowledge that consolidates instead of piling up.

Live 2026-10-03: "SQLite was first released in 2000" was stored as four
separate conclusions (#67, #77, #82, #102), one per quality run. A new
conclusion is compared with the stored conclusions about the same thing:

- same subject, same figures (or none) → a duplicate: not stored again, the
  existing entry is reinforced (journaled, so an objective that asked to
  learn it still sees the evidence);
- same subject, different figures (a year, a count) → a contradiction: it is
  stored, journaled as ``knowledge.contradiction`` and reported, and the
  autonomy cycle opens an objective to settle it with fresh research.

"Same subject" is keyword overlap (Jaccard ≥ SIMILAR) between the claims;
figures are the numbers in them. Words, not embeddings: no model is needed
and every decision can be read in the journal.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from syrax.journal import Journal

SIMILAR = 0.6
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?!\w|\.\d)")  # "2000." ends a sentence


def _words(text: str) -> set:
    from syrax.research import keywords

    return {w for w in keywords(text or "") if not w.isdigit()}


def figures(text: str) -> set:
    return set(NUMBER.findall(text or ""))


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def compare(claim: str, journal: Journal, limit: int = 300) -> Tuple[Optional[dict], List[dict]]:
    """(the stored conclusion this duplicates or None, conclusions it contradicts)."""
    mine = figures(claim)
    duplicate, conflicts = None, []
    for k in journal.knowledge_recent(limit=limit):
        if k.get("kind") != "conclusion" or similarity(claim, k["claim"]) < SIMILAR:
            continue
        theirs = figures(k["claim"])
        if mine and theirs and not (mine & theirs):
            conflicts.append(k)
        elif duplicate is None and (mine == theirs or not mine or not theirs or mine <= theirs or theirs <= mine):
            duplicate = k
    return (None if conflicts else duplicate), conflicts
