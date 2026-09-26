"""Experiments: two arms, measured, verdict from the numbers."""

import asyncio

import pytest

from app.tool.base import BaseTool, ToolResult
from app.tool.tool_collection import ToolCollection

from syrax.experiments import ExperimentEngine, ExperimentTool, judge, render
from syrax.journal import Journal


class Sleeper(BaseTool):
    name: str = "sleeper"
    description: str = "sleeps"
    parameters: dict = {"type": "object", "properties": {"ms": {"type": "number"}, "fail": {"type": "boolean"}}}

    async def execute(self, ms: float = 1, fail: bool = False) -> ToolResult:
        await asyncio.sleep(ms / 1000)
        return ToolResult(error="Error: told to fail") if fail else ToolResult(output="x" * int(ms))


def engine(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("experiment")
    coll = ToolCollection(Sleeper())
    return j, t, ExperimentEngine(j, lambda: coll, task_id_provider=lambda: t)


def test_faster_candidate_wins_on_ms(tmp_path):
    j, t, e = engine(tmp_path)
    row = asyncio.run(e.run("smaller sleep is faster", {"tool": "sleeper", "args": {"ms": 40}}, {"tool": "sleeper", "args": {"ms": 2}}, "ms", 2))
    assert row["verdict"] == "CANDIDATE_BETTER" and row["metric"] == "ms" and row["task_id"] == t
    assert row["baseline"]["value"] > row["candidate"]["value"] and len(row["baseline"]["samples"]) == 2
    assert "adopt the candidate" in row["next_action"]
    kinds = [e["type"] for e in j.events(t)]
    assert kinds[-2:] == ["experiment.started", "experiment.completed"]
    assert "CANDIDATE_BETTER" in render(row)


def test_output_len_and_success_metrics(tmp_path):
    j, t, e = engine(tmp_path)
    row = asyncio.run(e.run("more sleep, more output", {"tool": "sleeper", "args": {"ms": 2}}, {"tool": "sleeper", "args": {"ms": 30}}, "output_len", 1))
    assert row["verdict"] == "CANDIDATE_BETTER"
    row = asyncio.run(e.run("failing arm loses", {"tool": "sleeper", "args": {"ms": 1}}, {"tool": "sleeper", "args": {"ms": 1, "fail": True}}, "success", 2))
    assert row["verdict"] == "BASELINE_BETTER" and row["candidate"]["successes"] == 0
    row = asyncio.run(e.run("both fail", {"tool": "sleeper", "args": {"fail": True}}, {"tool": "sleeper", "args": {"fail": True}}, "ms", 1))
    assert row["verdict"] == "INCONCLUSIVE"
    row = asyncio.run(e.run("same thing", {"tool": "sleeper", "args": {"ms": 3}}, {"tool": "sleeper", "args": {"ms": 3}}, "output_len", 1))
    assert row["verdict"] == "NO_DIFFERENCE"
    assert j.count("experiments") == 4 and [x["verdict"] for x in j.experiments()][0] == "NO_DIFFERENCE"


def test_judge_edge_cases():
    b = {"successes": 1, "repeats": 1, "value": 0.0}
    c = {"successes": 1, "repeats": 1, "value": 0.0}
    assert judge("ms", b, c)[0] == "NO_DIFFERENCE"
    assert judge("ms", {**b, "value": 100}, {**c, "value": 95})[0] == "NO_DIFFERENCE"  # within noise
    assert judge("ms", {**b, "value": 100}, {**c, "value": 50})[0] == "CANDIDATE_BETTER"
    assert judge("ms", {**b, "value": 50}, {**c, "value": 100})[0] == "BASELINE_BETTER"
    assert judge("output_len", {**b, "value": 50}, {**c, "value": 100})[0] == "CANDIDATE_BETTER"
    assert judge("success", {**b, "successes": 2, "repeats": 3}, {**c, "successes": 3, "repeats": 3})[0] == "CANDIDATE_BETTER"


def test_validation_and_tool(tmp_path):
    j, t, e = engine(tmp_path)
    with pytest.raises(ValueError, match="hypothesis"):
        asyncio.run(e.run("", {"tool": "sleeper"}, {"tool": "sleeper"}))
    with pytest.raises(ValueError, match="metric"):
        asyncio.run(e.run("h", {"tool": "sleeper"}, {"tool": "sleeper"}, metric="vibes"))
    with pytest.raises(ValueError, match="unknown tool"):
        asyncio.run(e.run("h", {"tool": "ghost"}, {"tool": "sleeper"}))
    coll = ToolCollection(Sleeper(), ExperimentTool())
    e2 = ExperimentEngine(j, lambda: coll)
    with pytest.raises(ValueError, match="cannot be an experiment arm"):
        asyncio.run(e2.run("h", {"tool": "experiment"}, {"tool": "sleeper"}))
    tool = ExperimentTool()
    assert asyncio.run(tool.execute(hypothesis="h", baseline={"tool": "sleeper"}, candidate={"tool": "sleeper"})).error
    tool.engine = e
    out = asyncio.run(tool.execute(hypothesis="h", baseline={"tool": "sleeper", "args": {"ms": 1}}, candidate={"tool": "sleeper", "args": {"ms": 1}}, repeats=9))
    assert not out.error and "EXPERIMENT #" in out.output and "5 run(s)" in out.output  # repeats capped at 5
    assert asyncio.run(tool.execute(hypothesis="h", baseline={"tool": "nope"}, candidate={"tool": "sleeper"})).error
