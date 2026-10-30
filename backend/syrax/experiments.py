"""SYRAX experiment engine: baseline vs candidate, measured, journaled.

An experiment runs two tool invocations (or the same tool with different
arguments) under the same conditions, measures a chosen metric, and records
hypothesis, method, result, comparison and a conclusion computed from the
numbers. The model may phrase the hypothesis; it may not phrase the verdict.

Metrics:
  ms          wall-clock time of the tool call (lower is better)
  success     did the call succeed (ok and no "Error" in the output)
  output_len  length of the tool output (higher is better; use with care)
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import Field

from app.tool.base import BaseTool, ToolResult
from app.tool.tool_collection import ToolCollection

from syrax.journal import Journal, JournalError

METRICS = ("ms", "success", "output_len")
MAX_REPEATS = 5
NOISE_PCT = 10.0  # closer than this is NO_DIFFERENCE for ms / output_len

_ERR = re.compile(r"^(Error|Traceback)", re.M)


def _ok(result: Any) -> bool:
    text = str(result or "")
    err = getattr(result, "error", None)
    return not err and not _ERR.search(text) and "'success': False" not in text


ALPHA = 0.10  # the permutation p-value a difference must reach; with 3 runs per arm the smallest possible p is 0.10


def _check_arm(collection: ToolCollection, arm: dict) -> tuple:
    name = str(arm.get("tool") or "")
    args = arm.get("args") if isinstance(arm.get("args"), dict) else {}
    if name not in collection.tool_map:
        raise ValueError(f"unknown tool {name!r}")
    if name in ("release", "skill_create", "experiment", "compare_versions", "ask_human", "terminate"):
        raise ValueError(f"{name} cannot be an experiment arm")
    return name, args


async def _one(collection: ToolCollection, name: str, args: dict, metric: str) -> tuple:
    t0 = time.perf_counter()
    res = await collection.execute(name=name, tool_input=args)
    ms = (time.perf_counter() - t0) * 1000
    ok = _ok(res)
    text = str(res)
    return (ms if metric == "ms" else float(len(text)) if metric == "output_len" else float(ok)), ok, text[:300]


def _arm(name: str, args: dict, runs: List[tuple]) -> dict:
    samples = [r[0] for r in runs]
    return {"tool": name, "args": args, "repeats": len(runs), "samples": [round(x, 3) for x in samples],
            "value": round(sum(samples) / len(samples), 3), "successes": sum(1 for r in runs if r[1]), "last_output": runs[-1][2]}


async def run_arm(collection: ToolCollection, arm: dict, metric: str, repeats: int) -> dict:
    name, args = _check_arm(collection, arm)
    return _arm(name, args, [await _one(collection, name, args, metric) for _ in range(repeats)])


async def run_arms(collection: ToolCollection, baseline: dict, candidate: dict, metric: str, repeats: int, seed: str) -> tuple:
    """Both arms, interleaved: each repeat runs baseline and candidate once, in a seeded random order (EVOLUTION_PLAN
    wave 2, direction 114). All baseline runs before all candidate runs let a warming cache or a busier machine pass
    for an effect. The order is on record, and the same hypothesis gets the same order."""
    import random

    bn, ba = _check_arm(collection, baseline)
    cn, ca = _check_arm(collection, candidate)
    rng = random.Random(seed)
    b_runs, c_runs, order = [], [], []
    for _ in range(repeats):
        first_base = rng.random() < 0.5
        order.append("BC" if first_base else "CB")
        for which in ("B", "C") if first_base else ("C", "B"):
            if which == "B":
                b_runs.append(await _one(collection, bn, ba, metric))
            else:
                c_runs.append(await _one(collection, cn, ca, metric))
    return _arm(bn, ba, b_runs), _arm(cn, ca, c_runs), order


def permutation_p(a: List[float], b: List[float]) -> Optional[float]:
    """Exact two-sided permutation p-value of the difference of means (EVOLUTION_PLAN wave 2, direction 116): the share
    of all relabellings of the pooled samples whose mean difference is at least as large as the observed one. None when
    an arm has fewer than 2 samples. At most 5 + 5 samples here (252 relabellings)."""
    from itertools import combinations

    if len(a) < 2 or len(b) < 2:
        return None
    pooled, n = list(a) + list(b), len(a)
    observed = abs(sum(a) / len(a) - sum(b) / len(b))
    total = hits = 0
    for idx in combinations(range(len(pooled)), n):
        chosen = set(idx)
        x = [pooled[i] for i in idx]
        y = [pooled[i] for i in range(len(pooled)) if i not in chosen]
        total += 1
        hits += abs(sum(x) / len(x) - sum(y) / len(y)) >= observed - 1e-12
    return round(hits / total, 4)


def can_reach_alpha(n_a: int, n_b: int) -> bool:
    """Whether arms of these sizes can reach ALPHA at all: with 2 + 2 runs the smallest possible p is 0.33, so a
    significance test there could never pass, and the overlap rule decides instead (said in the conclusion)."""
    floor = permutation_p([float(i) for i in range(n_a)], [100.0 + i for i in range(n_b)])
    return floor is not None and floor <= ALPHA


def _overlap(base: dict, cand: dict) -> bool:
    """The arms' samples overlap: each arm ran at least twice and neither arm's range lies wholly beyond the other's."""
    b, c = base.get("samples") or [], cand.get("samples") or []
    return len(b) >= 2 and len(c) >= 2 and min(b) <= max(c) and min(c) <= max(b)


def judge(metric: str, base: dict, cand: dict, min_effect_pct: Optional[float] = None) -> tuple[str, str]:
    """The verdict from the numbers. ``min_effect_pct`` is the smallest change that counts, declared before the run
    (never below NOISE_PCT). 2026-10-29: when both arms ran at least twice and their samples overlap, the difference
    of the means is within the arms' own spread: NO_DIFFERENCE, whatever the means say."""
    threshold = max(NOISE_PCT, float(min_effect_pct or 0))
    if base["successes"] == 0 and cand["successes"] == 0:
        return "INCONCLUSIVE", "both arms failed on every run; nothing measured is comparable"
    if metric == "success":
        if cand["successes"] > base["successes"]:
            return "CANDIDATE_BETTER", f"candidate succeeded {cand['successes']}/{cand['repeats']} vs baseline {base['successes']}/{base['repeats']}"
        if cand["successes"] < base["successes"]:
            return "BASELINE_BETTER", f"baseline succeeded {base['successes']}/{base['repeats']} vs candidate {cand['successes']}/{cand['repeats']}"
        return "NO_DIFFERENCE", f"both succeeded {base['successes']}/{base['repeats']}"
    if base["successes"] != cand["successes"]:
        better = "CANDIDATE_BETTER" if cand["successes"] > base["successes"] else "BASELINE_BETTER"
        return better, f"success counts differ ({base['successes']} vs {cand['successes']}); the {metric} comparison is secondary"
    b, c = base["value"], cand["value"]
    if b == 0 and c == 0:
        return "NO_DIFFERENCE", f"both measured 0 {metric}"
    pct = (c - b) / b * 100 if b else float("inf")
    if abs(pct) <= threshold:
        return "NO_DIFFERENCE", f"{metric} within {threshold:.0f}% ({b:.3f} vs {c:.3f})"
    if _overlap(base, cand):
        return "NO_DIFFERENCE", (f"{metric}: means {b:.3f} vs {c:.3f} ({pct:+.1f}%), but the samples overlap "
                                 f"({min(base['samples'])}-{max(base['samples'])} vs {min(cand['samples'])}-{max(cand['samples'])})")
    bs, cs = base.get("samples") or [], cand.get("samples") or []
    p = permutation_p(bs, cs)
    tested = p is not None and can_reach_alpha(len(bs), len(cs))
    if tested and p > ALPHA:
        return "NO_DIFFERENCE", f"{metric}: means {b:.3f} vs {c:.3f} ({pct:+.1f}%), permutation p={p} > {ALPHA}"
    lower_better = metric == "ms"
    cand_better = (c < b) if lower_better else (c > b)
    note = (f", permutation p={p}" if tested else
            f", too few runs per arm for a significance test (p could not reach {ALPHA}); decided by the separated samples")
    return ("CANDIDATE_BETTER" if cand_better else "BASELINE_BETTER"), f"{metric}: baseline {b:.3f}, candidate {c:.3f} ({pct:+.1f}%){note}"


class ExperimentEngine:
    def __init__(self, journal: Journal, collection_provider: Callable[[], Optional[ToolCollection]],
                 task_id_provider: Optional[Callable[[], Optional[str]]] = None):
        self.journal = journal
        self.collection_provider = collection_provider
        self.task_id_provider = task_id_provider or (lambda: None)

    async def run(self, hypothesis: str, baseline: dict, candidate: dict, metric: str = "ms", repeats: int = 3,
                  objective: Optional[str] = None, min_effect_pct: Optional[float] = None) -> dict:
        if not (hypothesis or "").strip():
            raise ValueError("hypothesis required")
        if metric not in METRICS:
            raise ValueError(f"metric must be one of {', '.join(METRICS)}")
        repeats = max(1, min(int(repeats or 3), MAX_REPEATS))
        collection = self.collection_provider()
        if collection is None:
            raise ValueError("no tools available")
        task_id = self.task_id_provider()
        threshold = max(NOISE_PCT, float(min_effect_pct or 0))
        # the success criterion is on record before either arm runs: it cannot be chosen after seeing the numbers
        await self.journal.record("experiment.started", {"hypothesis": hypothesis[:160], "metric": metric, "repeats": repeats,
                                                         "min_effect_pct": threshold}, task_id=task_id)
        base, cand, order = await run_arms(collection, baseline, candidate, metric, repeats, seed=hypothesis)
        verdict, conclusion = judge(metric, base, cand, threshold)
        p = permutation_p(base["samples"], cand["samples"])
        next_action = {
            "CANDIDATE_BETTER": "adopt the candidate where it applies; keep the record as evidence",
            "BASELINE_BETTER": "keep the baseline; the hypothesis is not supported",
            "NO_DIFFERENCE": "no change justified by this evidence",
            "INCONCLUSIVE": "fix the failing arms before drawing any conclusion",
        }[verdict]
        row = await self.journal.run(
            self.journal.add_experiment_sync, hypothesis, base, cand, metric,
            {"baseline": base["value"], "candidate": cand["value"], "unit": metric, "repeats": repeats, "min_effect_pct": threshold,
             "order": order, "p_value": p, "alpha": ALPHA},
            conclusion, verdict, objective, next_action, task_id,
        )
        return row


def render(row: dict) -> str:
    b, c = row["baseline"], row["candidate"]
    return "\n".join([
        f"EXPERIMENT #{row['id']} {row['verdict']} · metric {row['metric']} · {row['result']['repeats']} run(s) per arm",
        f"hypothesis: {row['hypothesis']}",
        f"baseline  {b['tool']} {b['args']} → {b['value']} ({b['successes']}/{b['repeats']} ok) samples {b['samples']}",
        f"candidate {c['tool']} {c['args']} → {c['value']} ({c['successes']}/{c['repeats']} ok) samples {c['samples']}",
        f"conclusion: {row['conclusion']}",
        f"next: {row['next_action']}",
    ])


class ExperimentTool(BaseTool):
    name: str = "experiment"
    description: str = (
        "Run a controlled experiment: a baseline tool call and a candidate tool call, each repeated, "
        "measured on one metric (ms, success or output_len). The verdict is computed from the "
        "measurements and stored with the hypothesis; use it before claiming one approach is better."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "hypothesis": {"type": "string"},
            "baseline": {"type": "object", "properties": {"tool": {"type": "string"}, "args": {"type": "object"}}, "required": ["tool"]},
            "candidate": {"type": "object", "properties": {"tool": {"type": "string"}, "args": {"type": "object"}}, "required": ["tool"]},
            "metric": {"type": "string", "enum": list(METRICS), "description": "default ms"},
            "repeats": {"type": "integer", "description": "1-5, default 3; 2+ lets the verdict see the noise"},
            "min_effect_pct": {"type": "number", "description": "the smallest change (percent) that counts as better, "
                               "declared before the run; never below 10"},
            "objective": {"type": "string", "description": "what decision this informs"},
        },
        "required": ["hypothesis", "baseline", "candidate"],
    }
    engine: Optional[Any] = Field(default=None, exclude=True)

    async def execute(self, hypothesis: str, baseline: dict, candidate: dict, metric: str = "ms", repeats: int = 3,
                      objective: Optional[str] = None, min_effect_pct: Optional[float] = None) -> ToolResult:
        if self.engine is None:
            return ToolResult(error="experiment engine unavailable")
        try:
            row = await self.engine.run(hypothesis, baseline, candidate, metric, repeats, objective, min_effect_pct)
        except (ValueError, JournalError) as e:
            return ToolResult(error=f"experiment refused: {e}")
        return ToolResult(output=render(row))
