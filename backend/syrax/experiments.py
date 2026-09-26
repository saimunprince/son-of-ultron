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


async def run_arm(collection: ToolCollection, arm: dict, metric: str, repeats: int) -> dict:
    name = str(arm.get("tool") or "")
    args = arm.get("args") if isinstance(arm.get("args"), dict) else {}
    if name not in collection.tool_map:
        raise ValueError(f"unknown tool {name!r}")
    if name in ("release", "skill_create", "experiment", "ask_human", "terminate"):
        raise ValueError(f"{name} cannot be an experiment arm")
    samples: List[float] = []
    successes = 0
    outputs: List[str] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        res = await collection.execute(name=name, tool_input=args)
        ms = (time.perf_counter() - t0) * 1000
        ok = _ok(res)
        successes += ok
        text = str(res)
        outputs.append(text[:300])
        samples.append(ms if metric == "ms" else float(len(text)) if metric == "output_len" else float(ok))
    value = sum(samples) / len(samples)
    return {"tool": name, "args": args, "repeats": repeats, "samples": [round(s, 3) for s in samples], "value": round(value, 3),
            "successes": successes, "last_output": outputs[-1]}


def judge(metric: str, base: dict, cand: dict) -> tuple[str, str]:
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
    if abs(pct) <= NOISE_PCT:
        return "NO_DIFFERENCE", f"{metric} within {NOISE_PCT:.0f}% ({b:.3f} vs {c:.3f})"
    lower_better = metric == "ms"
    cand_better = (c < b) if lower_better else (c > b)
    return ("CANDIDATE_BETTER" if cand_better else "BASELINE_BETTER"), f"{metric}: baseline {b:.3f}, candidate {c:.3f} ({pct:+.1f}%)"


class ExperimentEngine:
    def __init__(self, journal: Journal, collection_provider: Callable[[], Optional[ToolCollection]],
                 task_id_provider: Optional[Callable[[], Optional[str]]] = None):
        self.journal = journal
        self.collection_provider = collection_provider
        self.task_id_provider = task_id_provider or (lambda: None)

    async def run(self, hypothesis: str, baseline: dict, candidate: dict, metric: str = "ms", repeats: int = 3,
                  objective: Optional[str] = None) -> dict:
        if not (hypothesis or "").strip():
            raise ValueError("hypothesis required")
        if metric not in METRICS:
            raise ValueError(f"metric must be one of {', '.join(METRICS)}")
        repeats = max(1, min(int(repeats or 3), MAX_REPEATS))
        collection = self.collection_provider()
        if collection is None:
            raise ValueError("no tools available")
        task_id = self.task_id_provider()
        await self.journal.record("experiment.started", {"hypothesis": hypothesis[:160], "metric": metric, "repeats": repeats}, task_id=task_id)
        base = await run_arm(collection, baseline, metric, repeats)
        cand = await run_arm(collection, candidate, metric, repeats)
        verdict, conclusion = judge(metric, base, cand)
        next_action = {
            "CANDIDATE_BETTER": "adopt the candidate where it applies; keep the record as evidence",
            "BASELINE_BETTER": "keep the baseline; the hypothesis is not supported",
            "NO_DIFFERENCE": "no change justified by this evidence",
            "INCONCLUSIVE": "fix the failing arms before drawing any conclusion",
        }[verdict]
        row = await self.journal.run(
            self.journal.add_experiment_sync, hypothesis, base, cand, metric,
            {"baseline": base["value"], "candidate": cand["value"], "unit": metric, "repeats": repeats},
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
            "repeats": {"type": "integer", "description": "1-5, default 3"},
            "objective": {"type": "string", "description": "what decision this informs"},
        },
        "required": ["hypothesis", "baseline", "candidate"],
    }
    engine: Optional[Any] = Field(default=None, exclude=True)

    async def execute(self, hypothesis: str, baseline: dict, candidate: dict, metric: str = "ms", repeats: int = 3,
                      objective: Optional[str] = None) -> ToolResult:
        if self.engine is None:
            return ToolResult(error="experiment engine unavailable")
        try:
            row = await self.engine.run(hypothesis, baseline, candidate, metric, repeats, objective)
        except (ValueError, JournalError) as e:
            return ToolResult(error=f"experiment refused: {e}")
        return ToolResult(output=render(row))
