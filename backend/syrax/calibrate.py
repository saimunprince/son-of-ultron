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


def _kind(o: dict) -> str:
    spec = o.get("check_spec") or {}
    return (spec.get("kind") if isinstance(spec, dict) else None) or "task_success"


def predicted_success(journal: Journal, kind: str, exclude: Optional[int] = None) -> float:
    """(done + a) / (finished + 2a) over finished objectives whose check kind is `kind` (a new kind starts at 0.5);
    a is prior_strength (1, Laplace, until tuning adopts another)."""
    a = prior_strength(journal)
    done = total = 0
    for o in journal.objectives(limit=ALL_OBJECTIVES, status=list(FINISHED)):
        if o["id"] == exclude or _kind(o) != kind:
            continue
        total += 1
        done += FINISHED[o["status"]]
    return round((done + a) / (total + 2 * a), 3)


# EVOLUTION_PLAN direction 87 (hyperparameter optimization): the prior's strength a is chosen from history, not by
# hand. Prequential: each finished objective is predicted only from the objectives that closed before it was created,
# so no score sees the future. Adopted only from TUNE_MIN objectives and a TUNE_MARGIN Brier gain over DEFAULT_PRIOR.
PRIOR_GRID = (0.5, 1.0, 2.0, 4.0, 6.0, 8.0)
DEFAULT_PRIOR = 1.0
TUNE_MIN = 30
TUNE_MARGIN = 0.003
PRIOR_META = "calibration_prior"


def prior_strength(journal: Journal) -> float:
    """The adopted prior strength (meta PRIOR_META, written by the autonomy's daily tuning), else DEFAULT_PRIOR."""
    import json

    try:
        t = json.loads(journal.get_meta(PRIOR_META) or "{}")
    except (TypeError, ValueError):
        return DEFAULT_PRIOR
    a = t.get("best") if t.get("adopted") else None
    return float(a) if a in PRIOR_GRID else DEFAULT_PRIOR


def prequential_brier(journal: Journal, a: float) -> tuple:
    """(Brier score, n) of predicting each finished objective from those closed before it was created, with prior a."""
    rows = [(o["created"], o["updated"], _kind(o), FINISHED[o["status"]])
            for o in journal.objectives(limit=ALL_OBJECTIVES, status=list(FINISHED))]
    if not rows:
        return None, 0
    closed = sorted((u, k, y) for _, u, k, y in rows)
    seen: Dict[str, List[int]] = {}
    i = se = 0
    for created, _, kind, y in sorted(rows):
        while i < len(closed) and closed[i][0] < created:
            st = seen.setdefault(closed[i][1], [0, 0])
            st[0] += closed[i][2]
            st[1] += 1
            i += 1
        d, t = seen.get(kind, [0, 0])
        se += ((d + a) / (t + 2 * a) - y) ** 2
    return round(se / len(rows), 4), len(rows)


def tune_prior(journal: Journal) -> dict:
    """The grid's best prior strength, its score, the default's score, n, and whether it is adopted."""
    scores = {a: prequential_brier(journal, a) for a in PRIOR_GRID}
    n = scores[DEFAULT_PRIOR][1]
    if not n:
        return {"best": DEFAULT_PRIOR, "score": None, "baseline": None, "n": 0, "adopted": False}
    best = min(PRIOR_GRID, key=lambda a: (scores[a][0], abs(a - DEFAULT_PRIOR)))
    base = scores[DEFAULT_PRIOR][0]
    adopted = n >= TUNE_MIN and best != DEFAULT_PRIOR and scores[best][0] <= base - TUNE_MARGIN
    return {"best": best if adopted else DEFAULT_PRIOR, "score": scores[best][0], "baseline": base, "n": n,
            "adopted": adopted, "grid": {str(a): scores[a][0] for a in PRIOR_GRID}}


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


def tool_priors(journal: Journal) -> Dict[str, tuple]:
    """Per tool, (predicted failure rate, real calls): (failures + 1) / (real calls + 2) over the calls that ran, the
    caller's own mistakes (journal.misuse) left out (EVOLUTION_PLAN wave 2, directions 37 environment prediction, 94
    tool selection). A tool never used starts at 0.5."""
    out = {}
    for name, st in journal.tool_stats().items():
        fails = max(0, st["failures"] - st.get("misuse", 0))
        n = st["successes"] + fails
        out[name] = (round((fails + 1) / (n + 2), 3), n)
    return out


def tool_pairs(journal: Journal, limit: int = 3000) -> List[tuple]:
    """(predicted failure, failed 1/0) for tool calls that carried a prediction; refused calls and misuse left out."""
    from syrax.journal import misuse

    out = []
    for kind, failed in (("tool.completed", 0), ("tool.failed", 1)):
        for e in journal.events_of_type(kind, limit=limit):
            p = e["payload"].get("predicted_failure")
            if not isinstance(p, (int, float)) or e["payload"].get("refused"):
                continue
            if failed and misuse(e["payload"].get("name"), e["payload"].get("output")):
                continue
            out.append((float(p), failed))
    return out


def summary(journal: Journal) -> dict:
    """{n, brier, bins, verdict, tools}: verdict is "no data", "well calibrated" (Brier <= 0.2), or "poorly calibrated";
    `tools` scores the per-call failure predictions the same way."""
    ps = pairs(journal)
    b = brier(ps)
    verdict = "no data" if b is None else ("well calibrated" if b <= 0.2 else "poorly calibrated")
    tp = tool_pairs(journal)
    return {"n": len(ps), "brier": b, "bins": bins(ps), "verdict": verdict,
            "tools": {"n": len(tp), "brier": brier(tp), "bins": bins(tp)}}
