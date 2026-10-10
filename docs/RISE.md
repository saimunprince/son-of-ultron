# SYRAX rise ledger

Generated 2026-10-10 13:04 by `python -m syrax.rise` at commit `b698cfe` from the journal (12793 events, 2026-09-30 15:18 to 2026-10-10 13:04). Every number is a read-only query over the journal; nothing here is typed by hand. **Last** is the last 7 days, **previous** the 7 days before, **trend** compares the two in the metric's own better direction. A dash means there is no evidence, which is reported as such.

The milestones in [EXECUTION_PLAN.md](EXECUTION_PLAN.md) are judged by these numbers.

## Brain

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Quality suite pass rate | 92.9 % (run #23, 14 cases) | 85.7 % (run #20, 14 cases) | 92.9 % (run #23, 14 cases) | higher | better |
| Machine-checked objectives done | 86.5 % (45/52) | 100 % (51/51) | 93.2 % (96/103) | higher | worse |
| Attempts per objective done | 1 (median of 45) | 1 (median of 51) | 1 (median of 96) | lower | same |
| Tool calls that failed | 5.9 % (34/576) | 10.2 % (59/580) | 8 % (93/1156) | lower | better |
| Own tasks left unfinished | 6.5 % (5/77) | 7 % (4/57) | 6.7 % (9/134) | lower | better |

- **Quality suite pass rate**: Latest full quality run (at least 10 cases) in the window: real tasks through the real brains, judged by checks on disk and in the journal.
- **Machine-checked objectives done**: Objectives closed in the window whose check is evidence (not task_success): DONE out of DONE + BLOCKED.
- **Attempts per objective done**: Median attempts of the machine-checked objectives closed DONE in the window.
- **Tool calls that failed**: tool.failed out of all finished tool calls in the window (refusals by a guard count as failures).
- **Own tasks left unfinished**: Autonomous tasks that ended PARTIAL (step limit, loop stop) or FAILED, out of all finished ones.

## Evolution

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Commits SYRAX made to itself | 3 | 0 | 3 | higher | better |
| Releases that landed | 60 % (3/5) | 0 % (0/5) | 30 % (3/10) | higher | better |
| Changes rolled back | 6 | 7 | 13 | lower | better |
| Changes a second brain rejected | 0 | 0 | 0 | - | — |
| Experiments run | 0 | 0 | 0 | higher | same |

- **Commits SYRAX made to itself**: commit.created: a change that passed the gate, a second brain's review, and was committed by SYRAX's release.
- **Releases that landed**: commit.created out of release calls in the window.
- **Changes rolled back**: rollback.created: an own change that failed the gate or the review, or a task that ended without releasing its edits.
- **Changes a second brain rejected**: review.completed with approve false.
- **Experiments run**: Rows in the experiments table: baseline against candidate, verdict computed from numbers.

## Memory

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Conclusions stored | 146 | 112 | 258 | - | — |
| Conclusions read back | 29 | 17 | 46 | higher | better |
| Conclusions reinforced or contradicted | 1 | 0 | 1 | - | — |

- **Conclusions stored**: knowledge.stored events (verified conclusions with sources).
- **Conclusions read back**: Stored conclusions whose last use falls in the window: memory that was used, not only kept.
- **Conclusions reinforced or contradicted**: knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.

## Evidence

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Final answers claiming work not done | 12 | 6 | 18 | lower | worse |
| Objectives closed on words | 4.3 % (2/47) | 0 % (0/51) | 2 % (2/98) | lower | worse |
| Gate verdicts GREEN | 100 % (3/3) | 100 % (1/1) | 100 % (4/4) | higher | same |
| Guards that held | 2 | 1 | 3 | - | — |

- **Final answers claiming work not done**: Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.
- **Objectives closed on words**: Objectives closed DONE whose check was only task_success.
- **Gate verdicts GREEN**: Journaled verifications that were GREEN.
- **Guards that held**: Releases refused for touching a judge or an existing test, and calls refused by the permission gate.

## Demonstration

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Days since the capability matrix was generated | 7 | 0 | 7 | lower | worse |

- **Days since the capability matrix was generated**: Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.
