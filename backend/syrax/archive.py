"""Phase 5 of the self-improvement plan: an archive of SYRAX's own variants, in
the manner of the Darwin Gödel Machine. Every release attempt is a row: the
commit it started from (parent), the commit it produced (head, for a committed
one), the decision, and later the score the quality suite measured at that
head. Parent selection picks the variant to build on next: a high score helps,
many children hurt (so the search does not pile onto one ancestor), and a
variant whose score is unknown waits for its quality run.

SYRAX runs main, so "building on a parent" means the autonomous brief names
it: the running build, its score and lineage, the best-scoring ancestor and
the dead ends this objective already produced. The archive is rendered into
docs/ARCHIVE.md by the daily ledger.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

from syrax.journal import Journal

DECISIONS = ("COMMITTED", "ROLLED_BACK", "REVIEW_REJECTED", "REFUSED", "COMMIT_FAILED")
MIDPOINT = 50.0  # pass rate where a variant is neither favoured nor penalised
SLOPE = 10.0  # pass-rate points per unit of the sigmoid
MAX_ROWS = 80


def record_attempt(journal: Journal, report: Dict[str, Any], summary: str, objective_id: Optional[int], task_id: Optional[str],
                   experiment_id: Optional[int]) -> Optional[dict]:
    """One release attempt → one archive row. Committed: head is the new commit; otherwise head is
    None and the row is a dead end hanging off its parent."""
    decision = str(report.get("outcome") or "UNKNOWN")
    if decision not in DECISIONS:
        return None
    parent = str(report.get("head") or "") or None
    head = str(report.get("commit") or "") if decision == "COMMITTED" else None
    return journal.add_archive_sync(head or None, parent, decision, summary.strip()[:200], objective_id, task_id, experiment_id)


def _short(sha: Optional[str]) -> str:
    return (sha or "")[:7] or "-"


def weight(score: Optional[float], children: int) -> float:
    """DGM-style: sigmoid of the score around the midpoint, divided by the children it already has."""
    if score is None:
        return 0.0
    return (1.0 / (1.0 + math.exp(-(float(score) - MIDPOINT) / SLOPE))) / (1 + children)


def variants(journal: Journal, limit: int = MAX_ROWS) -> List[dict]:
    """Archive rows newest first, each with its children count and selection weight."""
    rows = journal.archive(limit=limit)
    children: Dict[str, int] = {}
    for r in rows:
        if r.get("parent"):
            children[r["parent"]] = children.get(r["parent"], 0) + 1
    out = []
    for r in rows:
        kids = children.get(r["head"] or "", 0)
        out.append({**r, "children": kids, "weight": weight(r.get("score"), kids) if r.get("head") else 0.0})
    return out


def select_parent(journal: Journal) -> Optional[dict]:
    """The variant to build on next: the highest weight among committed, scored variants; the newest
    committed variant when none is scored yet (its score is still being measured)."""
    rows = [v for v in variants(journal) if v["head"] and v["decision"] == "COMMITTED"]
    if not rows:
        return None
    scored = [v for v in rows if v.get("score") is not None]
    if not scored:
        v = rows[0]
        return {**v, "why": "newest committed variant; no quality run has scored it yet"}
    best = max(scored, key=lambda v: (v["weight"], v["ts"]))
    return {**best, "why": f"score {best['score']:.0f}% with {best['children']} child(ren): weight {best['weight']:.3f}"}


def lineage(journal: Journal, head: Optional[str], depth: int = 8) -> List[dict]:
    """The chain of committed variants ending at `head`, newest first, as far as the archive knows."""
    by_head = {v["head"]: v for v in variants(journal, limit=500) if v["head"]}
    chain, cur = [], head
    while cur and cur in by_head and len(chain) < depth:
        chain.append(by_head[cur])
        cur = by_head[cur].get("parent")
    return chain


def dead_ends(journal: Journal, objective_id: Optional[int], limit: int = 4) -> List[dict]:
    if objective_id is None:
        return []
    return [v for v in variants(journal) if v["decision"] != "COMMITTED" and v.get("objective_id") == objective_id][:limit]


def brief(journal: Journal, running_head: Optional[str], objective_id: Optional[int] = None, budget: int = 700) -> str:
    """The archive, compact, for an autonomous brief about SYRAX's own code."""
    try:
        rows = variants(journal)
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["Archive of your own variants (DGM-style; the ledger renders it in docs/ARCHIVE.md):"]
    mine = next((v for v in rows if v["head"] and running_head and v["head"].startswith(running_head[:7])), None)
    if mine:
        lines.append(f"- running build {_short(mine['head'])}: score {mine['score']:.0f}%" if mine.get("score") is not None
                     else f"- running build {_short(mine['head'])}: not scored yet (run quality to score it)")
    best = select_parent(journal)
    if best:
        lines.append(f"- best parent to build on: {_short(best['head'])} ({best['why']}): {best['summary'][:80]}")
    for d in dead_ends(journal, objective_id):
        lines.append(f"- dead end for this objective: {d['decision']} from {_short(d['parent'])}: {d['summary'][:70]}")
    committed = sum(1 for v in rows if v["decision"] == "COMMITTED")
    lines.append(f"- {committed} committed variant(s), {len(rows) - committed} attempt(s) that did not land, in the last {len(rows)} rows.")
    return ("\n".join(lines) + "\n")[:budget]


def render(journal: Journal, head: str, generated: Optional[str] = None) -> str:
    generated = generated or time.strftime("%Y-%m-%d %H:%M %z")
    rows = variants(journal)
    best = select_parent(journal)
    lines = ["# SYRAX archive", "",
             f"Generated {generated} by the daily ledger at commit `{head}`, from the journal's `archive` table: every release "
             "attempt SYRAX made to its own code, the commit it started from, the commit it produced, and the quality score "
             "measured at that commit. Parent selection (Darwin Gödel Machine style) favours a high score and penalises an "
             "ancestor that already has many children. Nothing here is typed by hand.", ""]
    committed = [v for v in rows if v["decision"] == "COMMITTED"]
    lines.append(f"- Variants committed: {len(committed)}; attempts that did not land: {len(rows) - len(committed)}; scored: "
                 f"{sum(1 for v in committed if v.get('score') is not None)}.")
    if best:
        lines.append(f"- Best parent now: `{_short(best['head'])}` ({best['why']}).")
    chain = lineage(journal, head) or lineage(journal, next((v["head"] for v in committed), None))
    if chain:
        lines.append("- Lineage of the running build: " + " ← ".join(f"`{_short(v['head'])}`" + (f" {v['score']:.0f}%" if v.get("score") is not None else "") for v in chain))
    lines += ["", "| when | decision | parent → head | score | children | weight | objective | summary |", "|---|---|---|---|---|---|---|---|"]
    for v in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(v["ts"]))
        score = f"{v['score']:.0f}%" if v.get("score") is not None else "-"
        obj = f"#{v['objective_id']}" if v.get("objective_id") is not None else "-"
        lines.append(f"| {when} | {v['decision']} | `{_short(v['parent'])}` → `{_short(v['head'])}` | {score} | {v['children']} | {v['weight']:.3f} | {obj} | {v['summary'][:70].replace('|', '/')} |")
    if not rows:
        lines.append("| - | - | - | - | - | - | - | no release attempt recorded yet |")
    return "\n".join(lines).rstrip() + "\n"
