# SYRAX rise ledger

Generated 2026-10-17 10:49 by `python -m syrax.rise` at commit `09e97df` from the journal (34855 events, 2026-09-30 15:18 to 2026-10-17 10:49). Every number is a read-only query over the journal; nothing here is typed by hand. **Last** is the last 7 days, **previous** the 7 days before, **trend** compares the two in the metric's own better direction. A dash means there is no evidence, which is reported as such.

The milestones in [EXECUTION_PLAN.md](EXECUTION_PLAN.md) are judged by these numbers.

## Brain

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Quality suite pass rate | 92.2 % (run #43, 51 cases) | 92.9 % (run #23, 14 cases) | 92.2 % (run #43, 51 cases) | higher | worse |
| Machine-checked objectives done | 93.9 % (123/131) | 93.2 % (41/44) | 95 % (211/222) | higher | better |
| Attempts per objective done | 1 (median of 123) | 1 (median of 41) | 1 (median of 211) | lower | same |
| Tool calls that failed | 15.4 % (380/2464) | 5.5 % (23/417) | 13.4 % (460/3434) | lower | worse |
| Own tasks left unfinished | 11.9 % (29/243) | 4.8 % (3/62) | 10 % (36/359) | lower | worse |

- **Quality suite pass rate**: Latest full quality run (at least 10 cases) in the window: real tasks through the real brains, judged by checks on disk and in the journal.
- **Machine-checked objectives done**: Objectives closed in the window whose check is evidence (not task_success): DONE out of DONE + BLOCKED.
- **Attempts per objective done**: Median attempts of the machine-checked objectives closed DONE in the window.
- **Tool calls that failed**: tool.failed out of all finished tool calls in the window (refusals by a guard count as failures).
- **Own tasks left unfinished**: Autonomous tasks that ended PARTIAL (step limit, loop stop) or FAILED, out of all finished ones.

## Evolution

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Commits SYRAX made to itself | 10 | 2 | 12 | higher | better |
| Releases that landed | 16.4 % (10/61) | 33.3 % (2/6) | 17.1 % (12/70) | higher | worse |
| Own edits in the running tree | 27 | 19 | 52 | lower | worse |
| Changes rolled back | 61 | 3 | 70 | lower | worse |
| Changes a second brain rejected | 1 | 0 | 1 | - | — |
| Experiments run | 67 | 0 | 67 | higher | better |

- **Commits SYRAX made to itself**: commit.created: a change that passed the gate, a second brain's review, and was committed by SYRAX's release.
- **Releases that landed**: commit.created out of release calls in the window.
- **Own edits in the running tree**: Editor edits by SYRAX's own tasks that landed in the running tree instead of the task's isolated worktree (M1; every edit before it counts).
- **Changes rolled back**: rollback.created: an own change that failed the gate or the review, or a task that ended without releasing its edits.
- **Changes a second brain rejected**: review.completed with approve false.
- **Experiments run**: Rows in the experiments table: baseline against candidate, verdict computed from numbers.

## Memory

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Conclusions stored | 272 | 143 | 517 | - | — |
| Conclusions read back | 71 | 12 | 100 | higher | better |
| Conclusions reinforced or contradicted | 6 | 1 | 7 | - | — |

- **Conclusions stored**: knowledge.stored events (verified conclusions with sources).
- **Conclusions read back**: Stored conclusions whose last use falls in the window: memory that was used, not only kept.
- **Conclusions reinforced or contradicted**: knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.

## Evidence

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Final answers claiming work not done | 9 | 4 | 21 | lower | worse |
| False claims sent back | 11 | 0 | 11 | - | — |
| Objectives closed on words | 0 % (0/123) | 4.7 % (2/43) | 0.9 % (2/213) | lower | better |
| Gate verdicts GREEN | 46.4 % (13/28) | 100 % (2/2) | 51.6 % (16/31) | higher | worse |
| Guards that held | 73 | 2 | 76 | - | — |

- **Final answers claiming work not done**: Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.
- **False claims sent back**: claim.rejected: a final answer claimed work its task did not do and was sent back to be rewritten (journaled since M3).
- **Objectives closed on words**: Objectives closed DONE whose check was only task_success.
- **Gate verdicts GREEN**: Journaled verifications that were GREEN.
- **Guards that held**: Releases refused for touching a judge or an existing test, and calls refused by the permission gate.

## Demonstration

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Days since the capability matrix was generated | 2 | — | 2 | lower | — |

- **Days since the capability matrix was generated**: Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.
