# SYRAX rise ledger

Generated 2026-10-15 10:30 by `python -m syrax.rise` at commit `b3be3c2` from the journal (29759 events, 2026-09-30 15:18 to 2026-10-15 10:30). Every number is a read-only query over the journal; nothing here is typed by hand. **Last** is the last 7 days, **previous** the 7 days before, **trend** compares the two in the metric's own better direction. A dash means there is no evidence, which is reported as such.

The milestones in [EXECUTION_PLAN.md](EXECUTION_PLAN.md) are judged by these numbers.

## Brain

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Quality suite pass rate | 100 % (run #42, 10 cases) | 92.9 % (run #23, 14 cases) | 100 % (run #42, 10 cases) | higher | better |
| Machine-checked objectives done | 93.1 % (108/116) | 95.2 % (59/62) | 94.4 % (187/198) | higher | worse |
| Attempts per objective done | 1 (median of 108) | 1 (median of 59) | 1 (median of 187) | lower | same |
| Tool calls that failed | 15.4 % (311/2013) | 7.9 % (56/707) | 13.4 % (389/2896) | lower | worse |
| Own tasks left unfinished | 5.3 % (11/206) | 2.2 % (2/90) | 5.5 % (17/310) | lower | worse |

- **Quality suite pass rate**: Latest full quality run (at least 10 cases) in the window: real tasks through the real brains, judged by checks on disk and in the journal.
- **Machine-checked objectives done**: Objectives closed in the window whose check is evidence (not task_success): DONE out of DONE + BLOCKED.
- **Attempts per objective done**: Median attempts of the machine-checked objectives closed DONE in the window.
- **Tool calls that failed**: tool.failed out of all finished tool calls in the window (refusals by a guard count as failures).
- **Own tasks left unfinished**: Autonomous tasks that ended PARTIAL (step limit, loop stop) or FAILED, out of all finished ones.

## Evolution

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Commits SYRAX made to itself | 5 | 1 | 6 | higher | better |
| Releases that landed | 12.8 % (5/39) | 16.7 % (1/6) | 12.8 % (6/47) | higher | worse |
| Own edits in the running tree | 41 | 10 | 52 | lower | worse |
| Changes rolled back | 48 | 7 | 56 | lower | worse |
| Changes a second brain rejected | 0 | 0 | 0 | - | — |
| Experiments run | 44 | 0 | 44 | higher | better |

- **Commits SYRAX made to itself**: commit.created: a change that passed the gate, a second brain's review, and was committed by SYRAX's release.
- **Releases that landed**: commit.created out of release calls in the window.
- **Own edits in the running tree**: Editor edits by SYRAX's own tasks that landed in the running tree instead of the task's isolated worktree (M1; every edit before it counts).
- **Changes rolled back**: rollback.created: an own change that failed the gate or the review, or a task that ended without releasing its edits.
- **Changes a second brain rejected**: review.completed with approve false.
- **Experiments run**: Rows in the experiments table: baseline against candidate, verdict computed from numbers.

## Memory

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Conclusions stored | 223 | 188 | 439 | - | — |
| Conclusions read back | 52 | 23 | 81 | higher | better |
| Conclusions reinforced or contradicted | 3 | 1 | 4 | - | — |

- **Conclusions stored**: knowledge.stored events (verified conclusions with sources).
- **Conclusions read back**: Stored conclusions whose last use falls in the window: memory that was used, not only kept.
- **Conclusions reinforced or contradicted**: knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.

## Evidence

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Final answers claiming work not done | 9 | 9 | 18 | lower | same |
| False claims sent back | 9 | 0 | 9 | - | — |
| Objectives closed on words | 0 % (0/108) | 3.3 % (2/61) | 1.1 % (2/189) | lower | better |
| Gate verdicts GREEN | 33.3 % (7/21) | 100 % (1/1) | 39.1 % (9/23) | higher | worse |
| Guards that held | 50 | 3 | 53 | - | — |

- **Final answers claiming work not done**: Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.
- **False claims sent back**: claim.rejected: a final answer claimed work its task did not do and was sent back to be rewritten (journaled since M3).
- **Objectives closed on words**: Objectives closed DONE whose check was only task_success.
- **Gate verdicts GREEN**: Journaled verifications that were GREEN.
- **Guards that held**: Releases refused for touching a judge or an existing test, and calls refused by the permission gate.

## Demonstration

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Days since the capability matrix was generated | 1 | — | 1 | lower | — |

- **Days since the capability matrix was generated**: Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.
