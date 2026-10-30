"""Confidence calibration (EVOLUTION_PLAN wave 2, directions 22 confidence calibration, 30 metacognitive calibration,
282 metacognitive access): SYRAX stated how likely an objective was to succeed nowhere, and so never learned whether its
expectations were right. Now every goal.selected carries `predicted_success`: the Laplace-smoothed success rate of
earlier objectives with the same check kind. Once an objective ends (DONE = 1, BLOCKED or DROPPED = 0) the pair is
scored: the Brier score (0 is perfect, 0.25 is a coin) and reliability bins show where it over- or under-expects.

A judge (devloop.JUDGES): what measures SYRAX must not be edited by SYRAX. Pure reads of the journal."""

from __future__ import annotations

from typing import Dict, List, Optional

from syrax.journal import ALL_OBJECTIVES, Journal

FINISHED = {"DONE": 1, "BLOCKED": 0, "DROPPED": 0}
BINS = 5


def predicted_success(journal: Journal, kind: str, exclude: Optional[int] = None) -> float:
    """(done + 1) / (finished + 2) over finished objectives whose check kind is `kind` (a new kind starts at 0.5)."""
    done = total = 0
    for o in journal.objectives(limit=ALL_OBJECTIVES, status=list(FINISHED)):
        if o["id"] == exclude or ((o.get("check_spec") or {}).get("kind") or "task_success") != kind:
            continue
        total += 1
        done += FINISHED[o["status"]]
    return round((done + 1) / (total + 2), 3)


def pairs(journal: Journal, limit: int = 2000) -> List[tuple]:
    """(predicted, outcome) for each finished objective, from its last selection that stated a prediction."""
    last: Dict[int, float] = {}
    for e in reversed(journal.events_of_type("goal.selected", limit=limit)):  # oldest first: the last one wins
        p = e["payload"].get("predicted_success")
        oid = e["payload"].get("objective_id")
        if isinstance(p, (int, float)) and oid is not None:
            last[oid] = float(p)
    out = []
    for oid, p in last.items():
        o = journal.objective(int(oid))
        if o and o["status"] in FINISHED:
            out.append((p, FINISHED[o["status"]]))
    return out


def brier(ps: List[tuple]) -> Optional[float]:
    return round(sum((p - y) ** 2 for p, y in ps) / len(ps), 4) if ps else None


def bins(ps: List[tuple], k: int = BINS) -> List[dict]:
    out = []
    for i in range(k):
        lo, hi = i / k, (i + 1) / k
        inside = [(p, y) for p, y in ps if lo <= p < hi or (i == k - 1 and p == 1.0)]
        if inside:
            out.append({"from": round(lo, 2), "to": round(hi, 2), "n": len(inside),
                        "predicted": round(sum(p for p, _ in inside) / len(inside), 3),
                        "observed": round(sum(y for _, y in inside) / len(inside), 3)})
    return out


def summary(journal: Journal) -> dict:
    """{n, brier, bins, verdict}: verdict is "no data", "well calibrated" (Brier <= 0.2), or "poorly calibrated"."""
    ps = pairs(journal)
    b = brier(ps)
    verdict = "no data" if b is None else ("well calibrated" if b <= 0.2 else "poorly calibrated")
    return {"n": len(ps), "brier": b, "bins": bins(ps), "verdict": verdict}
