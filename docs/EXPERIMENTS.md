# SYRAX Experiments, Benchmarks and Recursive Self-Improvement

Implemented in `backend/syrax/bench.py`, `backend/syrax/experiments.py`, the
`benchmarks` / `experiments` tables, the performance gate in `syrax/verify.py`
and the Phase-12 derivations in `syrax/autonomy.py`. Tests: `test_bench.py`,
`test_experiments.py`, `test_autonomy.py` (self-improvement section), `test_bridge.py`.

## Benchmarks (`python -m syrax.bench`)

Measured on a scratch journal so the real one is untouched:

| metric | what |
|---|---|
| journal_record_p50_ms / p95 | one durable event write (BEGIN…COMMIT + fsync) |
| checkpoint_p95_ms | checkpoint with a 40-message context |
| tool_stats_ms | the capability registry query over 600 events |
| events_between_ms | a replay window query |
| recovery_ms | recovery of 20 interrupted tasks at open |
| selfmodel_summary_ms | `SelfModel.snapshot("summary")` |

Each run is compared with the previous stored run: a metric that is slower by
more than 50 % **and** more than 5 ms is a regression. The first run is a
BASELINE, not a PASS. Results are stored in `benchmarks` with `compared_to`
and per-metric deltas; `benchmark.completed` is journaled.

The release gate's `performance` gate runs the suite and fails on REGRESSION.
It is recorded and reported but stays optional (not required for GREEN), because
a laptop under load can produce false regressions; a required gate would block
releases on noise. The regression is still a measured weakness (below).

## Task-quality benchmark (`quality_run`)

`backend/syrax/quality.py` runs ten fixed tasks through the real core and
brain and checks the outcome by machine only: the final text (regex), which
tools ran, and file contents. Cases: arithmetic, python tool use, file create,
file edit, self-version via `self_inspect`, CPU count via `desktop`, restraint
(one word, no tools), `present` a table, honest `know`, `research` with a
source. Each run stores per-case evidence and a pass rate in `quality_runs`;
a drop of more than 15 percentage points against the previous run is a
REGRESSION, the first run is a BASELINE. Eval tasks have `kind = "eval"` and
never enter the conversation history. It costs model calls (about a minute
per case on the free brain) and needs an idle core, so it is on demand:
WebSocket `quality_run {only?}` / `quality_runs`, never part of the release
gate. A regression becomes an objective (`quality_recovered`) that closes only
when a newer run is not a regression; the self-model lists the last run under
`performance.last_quality` and failing cases as a weakness.

## Experiments (`experiment` tool)

```
experiment {hypothesis, baseline {tool, args}, candidate {tool, args}, metric ms|success|output_len, repeats 1-5}
```

Both arms run through the real tool collection, repeated, timed. The verdict
is computed from the numbers: CANDIDATE_BETTER / BASELINE_BETTER /
NO_DIFFERENCE (within 10 %) / INCONCLUSIVE (both arms failed). The record
holds hypothesis, method (tools, args, repeats), samples, result, conclusion
and next action. The model chooses the hypothesis; it cannot choose the verdict.
`release`, `skill_create`, `experiment`, `ask_human` and `terminate` cannot be arms.

## Objectives about SYRAX's own mechanisms

Derived every cycle (idempotent):

| evidence | objective | closes when |
|---|---|---|
| latest benchmark is REGRESSION | fix the regressed metric and release | a newer benchmark shows no regression for that metric |
| ≥ 2 BLOCKED objectives about the same tool | research a genuinely different approach | knowledge about "<tool> alternative approach" is stored |
| knowledge used ≥ 3 times with confidence < 0.5 | corroborate or refute it | newer knowledge with shared tags reaches confidence ≥ 0.6 |

Together with the existing derivations (untested tools, failing tools, blocked
verification, researchable failures, uncertain interrupted tasks) these form the
loop: measure → weakness → objective → research/experiment/build → gate → evidence.

## Self-model

`performance` section: last benchmark (status, metrics, regressions), benchmark
count, experiment count and recent verdicts. A benchmark regression is listed as
a weakness with evidence `journal.benchmarks`.

## Limits

- The task-quality suite is small (10 cases) and brain-dependent; it measures outcomes, not reasoning quality.
- Experiments measure tool calls, not code changes; changing code and measuring is still research → `release`.
- Objectives are executed by the same agent with the same tools; "fix the regression" depends on the model finding the cause.
