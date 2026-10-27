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

Every stored conclusion is compared, not the most recent rows of every kind
(audit 2026-10-27: web rows filled the last 300, so "SQLite was first released
in 2000" came back as new 412 rows later and is stored ten times). A duplicate
stays a duplicate when another stored conclusion contradicts the claim: it is
reinforced, not stored again, and the contradiction is still reported (the
same audit found three identical ethanol rows stored because a conflict
skipped the duplicate check).

"Same subject" is keyword overlap (Jaccard ≥ SIMILAR) between the claims;
figures are the numbers in them. Words, not embeddings: no model is needed
and every decision can be read in the journal.

Two figures are the same figure when they ``agree`` (live 2026-10-19..26:
"approximately 78.4°C (173.1°F)" against "78.37°C" opened three contradiction
objectives that research could never settle, because both are right):

- equal values, thousands separators ignored ("1,442" is 1442);
- the more precise one rounds (half up) to the less precise one
  (78.37 → 78.4, 78.37 → 78);
- they differ by less than TOLERANCE (0.5 %) of the larger, when at least one
  has decimals and both are ≥ SMALL. Whole numbers (years, counts) are exact:
  2000 vs 2004 and 1442 vs 1443 stay contradictions. Below SMALL a decimal is
  as often a version or a ratio (Python 3.12 vs 3.13) as a measurement, so
  there only rounding counts.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import List, Optional, Tuple

from syrax.journal import Journal

SIMILAR = 0.6
TOLERANCE = Decimal("0.005")
SMALL = 10
# "2000." ends a sentence; "1,442" is one figure, "1,2345" is still two
NUMBER = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+(?!\d)|\d+)(?:\.\d+)?(?!\w|\.\d)")


def _words(text: str) -> set:
    from syrax.research import keywords

    return {w for w in keywords(text or "") if not w.isdigit()}


def figures(text: str) -> set:
    return {m.replace(",", "") for m in NUMBER.findall(text or "")}


def _places(figure: str) -> int:
    return len(figure.partition(".")[2])


def agree(a: str, b: str) -> bool:
    """True when two figures state the same value (see the module doc)."""
    try:
        x, y = Decimal(a.replace(",", "")), Decimal(b.replace(",", ""))
        if x == y:
            return True
        pa, pb = _places(a), _places(b)
        if pa != pb:
            fine, coarse, p = (x, y, pb) if pa > pb else (y, x, pa)
            if fine.quantize(Decimal(1).scaleb(-p), rounding=ROUND_HALF_UP) == coarse:
                return True
        if not (pa or pb) or min(x, y) < SMALL:
            return False
        return abs(x - y) < TOLERANCE * max(x, y)
    except (InvalidOperation, ValueError):
        return a == b


def _overlap(mine: set, theirs: set) -> bool:
    return any(agree(a, b) for a in mine for b in theirs)


def _covered(some: set, by: set) -> bool:
    return all(any(agree(a, b) for b in by) for a in some)


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def compare(claim: str, journal: Journal, limit: int = 5000) -> Tuple[Optional[dict], List[dict]]:
    """(the stored conclusion this duplicates or None, conclusions it contradicts), over every stored
    conclusion (newest first). Both can be set: a duplicate is reported even when another row conflicts."""
    mine = figures(claim)
    duplicate, conflicts = None, []
    for k in reversed(journal.knowledge_of_kind(("conclusion",), limit=limit)):
        if similarity(claim, k["claim"]) < SIMILAR:
            continue
        theirs = figures(k["claim"])
        if mine and theirs and not _overlap(mine, theirs):
            conflicts.append(k)
        elif duplicate is None and (not mine or not theirs or _covered(mine, theirs) or _covered(theirs, mine)):
            duplicate = k
    return duplicate, conflicts
