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

The state of a row is kept on the row (audit 2026-10-27, item 4: DISPUTED was
recomputed from the last events and aged out):

- a contradiction marks the rows involved DISPUTED (``knowledge.disputed``,
  journaled with the ``knowledge.contradiction`` that found it); ``know``
  shows them marked, never as fact;
- a later ``learn`` settles it (``settles``) when a row involved is already
  DISPUTED and the claim rests on ``independent`` evidence (a stored source row,
  not a conclusion, whose text fully supports the claim and that none of the
  rows involved already rests on) at least as strong as every row it
  contradicts: the row the claim confirms (or the new row) becomes ACTIVE and
  verified, the rows it contradicts SUPERSEDED (``superseded_by``);
- a DISPUTED row confirmed by independent evidence with nothing left to
  contradict it is resolved back to ACTIVE;
- SUPERSEDED rows are history: they are compared with nothing.

Citing the same rows again settles nothing: the evidence must be new.

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
from typing import Iterable, List, Optional, Set, Tuple

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


# Non-numeric contradictions (EVOLUTION_PLAN direction 10): only differing figures were caught. Relations that have a
# single answer per subject ("Python 3.12 was released in October 2023" vs "... in October 2024") contradict when the
# same subject gets two different objects, whatever the wording (journal.links_of extracts them).
FUNCTIONAL = ("was released in", "was created by", "is written in")


def _functional(claim: str) -> dict:
    from syrax.journal import links_of

    return {(s, r): o for s, r, o in links_of(claim) if r in FUNCTIONAL}


def _disagree(mine: dict, theirs: dict) -> bool:
    return any(k in theirs and theirs[k] != o and not (o in theirs[k] or theirs[k] in o) for k, o in mine.items())


def compare(claim: str, journal: Journal, limit: int = 5000) -> Tuple[Optional[dict], List[dict]]:
    """(the stored conclusion this duplicates or None, conclusions it contradicts), over every stored
    conclusion that is not SUPERSEDED (newest first). Both can be set: a duplicate is reported even when another
    row conflicts."""
    mine = figures(claim)
    my_facts = _functional(claim)
    duplicate, conflicts = None, []
    for k in reversed(journal.knowledge_of_kind(("conclusion",), limit=limit)):
        if k.get("status") == "SUPERSEDED":
            continue
        if my_facts and _disagree(my_facts, _functional(k["claim"])):
            conflicts.append(k)  # the same thing given two different values: a contradiction however worded
            continue
        if similarity(claim, k["claim"]) < SIMILAR:
            continue
        theirs = figures(k["claim"])
        if mine and theirs and not _overlap(mine, theirs):
            conflicts.append(k)
        elif duplicate is None and (not mine or not theirs or _covered(mine, theirs) or _covered(theirs, mine)):
            duplicate = k
    return duplicate, conflicts


def _rests_on(rows: Iterable[dict]) -> Set[int]:
    """The rows themselves and every stored row they cite."""
    out: Set[int] = set()
    for k in rows:
        out.add(int(k["id"]))
        out |= {int(x) for x in k.get("sources") or [] if isinstance(x, int) or str(x).isdigit()}
    return out


def independent(cited: Iterable[dict], full: Set[int], involved: Iterable[dict]) -> List[dict]:
    """The cited rows that are new evidence about the rows `involved`: a source (not a conclusion), not SUPERSEDED,
    whose text fully supports the claim (its id is in `full`), and neither one of the involved rows nor a row they
    already cite."""
    seen = _rests_on(involved)
    return [k for k in cited if k and k["id"] in full and k["kind"] != "conclusion"
            and k.get("status") != "SUPERSEDED" and int(k["id"]) not in seen]


def settles(duplicate: Optional[dict], conflicts: List[dict], fresh: List[dict]) -> bool:
    """True when a claim settles a dispute in its favour: it contradicts stored rows, a row involved (the one it
    duplicates or one it contradicts) is already DISPUTED, and its strongest independent evidence (`fresh`) is at
    least as strong as every row it contradicts. A first contradiction is never settled on the spot: it is
    disputed and journaled first."""
    if not conflicts or not fresh:
        return False
    involved = ([duplicate] if duplicate else []) + list(conflicts)
    if not any(k.get("status") == "DISPUTED" for k in involved):
        return False
    return max(k["confidence"] for k in fresh) >= max(k["confidence"] for k in conflicts)
