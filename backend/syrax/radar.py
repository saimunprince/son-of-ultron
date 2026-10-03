"""Phase 6 — technology radar, first step: new models on SYRAX's own brains.

"SYRAX will not stay frozen in a 2026 codebase." Once a day, when nothing else
is open, SYRAX lists the models each enabled brain offers, compares them with
the list it saw last time (journal meta), tool-call tests a few new ones, and
turns the working ones into proposals for the human. The first scan of a
provider only records a baseline: testing a whole catalogue would burn the
free quotas the radar is meant to protect.

Discover → relevant? (tool calling, the one capability SYRAX cannot work
without) → experiment (a tiny tool call, timed) → propose. Adopting a model
stays the human's choice.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from syrax.journal import Journal

EVERY_S = 24 * 3600.0
MAX_TESTS = 3
LAST_KEY = "radar_last"


def due(journal: Journal, now: Optional[float] = None) -> bool:
    try:
        last = float(journal.get_meta(LAST_KEY) or 0)
    except ValueError:
        last = 0.0
    return (now or time.time()) - last >= EVERY_S


async def scan(router: Any, journal: Journal, now: Optional[float] = None, max_tests: int = MAX_TESTS) -> Dict[str, Any]:
    """One radar pass. Returns {new: {pid: [...]}, tested: [...], baselined: [...]}."""
    now = now or time.time()
    journal.set_meta(LAST_KEY, str(now))
    report: Dict[str, Any] = {"new": {}, "tested": [], "baselined": []}
    budget = max_tests
    for pid in list(router.store.order):
        if not router.store.enabled(pid):
            continue
        try:
            models: List[str] = await asyncio.wait_for(router.list_models(pid), 30)
        except Exception:
            continue
        key = f"radar_models:{pid}"
        raw = journal.get_meta(key)
        journal.set_meta(key, json.dumps(sorted(models)))
        if raw is None:
            report["baselined"].append(pid)
            continue
        known = set(json.loads(raw))
        new = [m for m in models if m not in known]
        if not new:
            continue
        report["new"][pid] = new
        journal.record_sync("radar.new_models", {"provider": pid, "models": new[:20]})
        for model in new:
            if budget <= 0:
                break
            budget -= 1
            try:
                res = await asyncio.wait_for(router.test(pid, model=model), 90)
            except Exception as e:
                res = {"id": pid, "ok": False, "error": str(e)[:200]}
            row = {"provider": pid, "model": model, "ok": bool(res.get("ok")), "tools": bool(res.get("tools")),
                   "latency_ms": res.get("latency_ms"), "error": res.get("error")}
            report["tested"].append(row)
            journal.record_sync("radar.tested", row)
            if row["ok"] and row["tools"]:
                journal.record_sync("proposal.created", {
                    "kind": "technology_radar", "limitation": f"a new model appeared on {pid}",
                    "proposal": f"{model} is new on {pid} and makes tool calls ({row['latency_ms']} ms in a tiny test). "
                                f"It could replace or back up the current {pid} model ({router.store.model(pid)}); "
                                f"a quality run with it would show whether it is better.",
                    "sources": [],
                })
    try:  # Phase 3: requests the human keeps repeating become skill proposals
        from syrax import skillevo

        report["skill_candidates"] = skillevo.propose_candidates(journal, now)
    except Exception:
        pass
    try:  # the daily pass also checks whether the brain order matches measured quality
        from syrax import scorecard

        prop = scorecard.daily_proposal(journal, list(router.store.order))
        if prop:
            report["order_proposal"] = prop["limitation"]
    except Exception:
        pass
    return report
