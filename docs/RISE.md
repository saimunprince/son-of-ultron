# SYRAX rise ledger

Generated 2026-10-25 11:43 by `python -m syrax.rise` at commit `0ab288e` from the journal (48109 events, 2026-09-30 15:18 to 2026-10-25 11:43). Every number is a read-only query over the journal; nothing here is typed by hand. **Last** is the last 7 days, **previous** the 7 days before, **trend** compares the two in the metric's own better direction. A dash means there is no evidence, which is reported as such.

The milestones in [EXECUTION_PLAN.md](EXECUTION_PLAN.md) are judged by these numbers.

## Brain

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Quality suite pass rate | 90.4 % (run #58, 52 cases) | 88.2 % (run #46, 51 cases) | 90.4 % (run #58, 52 cases) | higher | better |
| Machine-checked objectives done | 94.4 % (34/36) | 98.2 % (110/112) | 98.4 % (250/254) | higher | worse |
| Attempts per objective done | 1 (median of 34) | 1 (median of 110) | 1 (median of 250) | lower | same |
| Tool calls that failed | 9.5 % (101/1064) | 15.9 % (394/2472) | 12.4 % (589/4740) | lower | better |
| Own tasks left unfinished | 2 % (1/49) | 12.3 % (28/228) | 9.1 % (38/417) | lower | better |

- **Quality suite pass rate**: Latest full quality run (at least 10 cases) in the window: real tasks through the real brains, judged by checks on disk and in the journal.
- **Machine-checked objectives done**: Objectives closed in the window whose check is evidence (not task_success): DONE out of DONE + BLOCKED.
- **Attempts per objective done**: Median attempts of the machine-checked objectives closed DONE in the window.
- **Tool calls that failed**: tool.failed out of all finished tool calls in the window (refusals by a guard count as failures).
- **Own tasks left unfinished**: Autonomous tasks that ended PARTIAL (step limit, loop stop) or FAILED, out of all finished ones.

## Evolution

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Commits SYRAX made to itself | 12 | 14 | 30 | higher | worse |
| Releases that landed | 37.5 % (12/32) | 22.6 % (14/62) | 26.3 % (30/114) | higher | better |
| Own edits in the running tree | 0 | 2 | 52 | lower | better |
| Changes rolled back | 39 | 59 | 120 | lower | better |
| Changes a second brain rejected | 1 | 1 | 2 | - | — |
| Experiments run | 26 | 68 | 103 | higher | worse |

- **Commits SYRAX made to itself**: commit.created: a change that passed the gate, a second brain's review, and was committed by SYRAX's release.
- **Releases that landed**: commit.created out of release calls in the window.
- **Own edits in the running tree**: Editor edits by SYRAX's own tasks that landed in the running tree instead of the task's isolated worktree (M1; every edit before it counts).
- **Changes rolled back**: rollback.created: an own change that failed the gate or the review, or a task that ended without releasing its edits.
- **Changes a second brain rejected**: review.completed with approve false.
- **Experiments run**: Rows in the experiments table: baseline against candidate, verdict computed from numbers.

## Memory

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Conclusions stored | 112 | 257 | 642 | - | — |
| Conclusions read back | 31 | 63 | 125 | higher | worse |
| Conclusions reinforced or contradicted | 12 | 6 | 19 | - | — |

- **Conclusions stored**: knowledge.stored events (verified conclusions with sources).
- **Conclusions read back**: Stored conclusions whose last use falls in the window: memory that was used, not only kept.
- **Conclusions reinforced or contradicted**: knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.

## Evidence

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Final answers claiming work not done | 0 | 1 | 21 | lower | better |
| False claims sent back | 4 | 12 | 16 | - | — |
| Objectives closed on words | 0 % (0/34) | 0 % (0/110) | 0.8 % (2/252) | lower | same |
| Gate verdicts GREEN | 100 % (13/13) | 70.8 % (17/24) | 68.6 % (35/51) | higher | better |
| Guards that held | 31 | 81 | 115 | - | — |

- **Final answers claiming work not done**: Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.
- **False claims sent back**: claim.rejected: a final answer claimed work its task did not do and was sent back to be rewritten (journaled since M3).
- **Objectives closed on words**: Objectives closed DONE whose check was only task_success.
- **Gate verdicts GREEN**: Journaled verifications that were GREEN.
- **Guards that held**: Releases refused for touching a judge or an existing test, and calls refused by the permission gate.

## Demonstration

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Days since the capability matrix was generated | 3 | — | 3 | lower | — |

- **Days since the capability matrix was generated**: Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.
