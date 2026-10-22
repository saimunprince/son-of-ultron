# SYRAX rise ledger

Generated 2026-10-22 12:25 by `python -m syrax.rise` at commit `9a9b640` from the journal (45676 events, 2026-09-30 15:18 to 2026-10-22 12:25). Every number is a read-only query over the journal; nothing here is typed by hand. **Last** is the last 7 days, **previous** the 7 days before, **trend** compares the two in the metric's own better direction. A dash means there is no evidence, which is reported as such.

The milestones in [EXECUTION_PLAN.md](EXECUTION_PLAN.md) are judged by these numbers.

## Brain

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Quality suite pass rate | 96.2 % (run #54, 52 cases) | 100 % (run #42, 10 cases) | 96.2 % (run #54, 52 cases) | higher | worse |
| Machine-checked objectives done | 96.4 % (54/56) | 98.2 % (107/109) | 98.4 % (244/248) | higher | worse |
| Attempts per objective done | 1 (median of 54) | 1 (median of 107) | 1 (median of 244) | lower | same |
| Tool calls that failed | 9.1 % (134/1472) | 16.1 % (346/2150) | 12.4 % (558/4518) | lower | better |
| Own tasks left unfinished | 18.9 % (17/90) | 7.1 % (15/211) | 9.3 % (38/410) | lower | worse |

- **Quality suite pass rate**: Latest full quality run (at least 10 cases) in the window: real tasks through the real brains, judged by checks on disk and in the journal.
- **Machine-checked objectives done**: Objectives closed in the window whose check is evidence (not task_success): DONE out of DONE + BLOCKED.
- **Attempts per objective done**: Median attempts of the machine-checked objectives closed DONE in the window.
- **Tool calls that failed**: tool.failed out of all finished tool calls in the window (refusals by a guard count as failures).
- **Own tasks left unfinished**: Autonomous tasks that ended PARTIAL (step limit, loop stop) or FAILED, out of all finished ones.

## Evolution

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Commits SYRAX made to itself | 20 | 6 | 27 | higher | better |
| Releases that landed | 35.7 % (20/56) | 13.6 % (6/44) | 25 % (27/108) | higher | better |
| Own edits in the running tree | 0 | 41 | 52 | lower | better |
| Changes rolled back | 54 | 52 | 114 | lower | worse |
| Changes a second brain rejected | 1 | 0 | 1 | - | — |
| Experiments run | 46 | 50 | 96 | higher | worse |

- **Commits SYRAX made to itself**: commit.created: a change that passed the gate, a second brain's review, and was committed by SYRAX's release.
- **Releases that landed**: commit.created out of release calls in the window.
- **Own edits in the running tree**: Editor edits by SYRAX's own tasks that landed in the running tree instead of the task's isolated worktree (M1; every edit before it counts).
- **Changes rolled back**: rollback.created: an own change that failed the gate or the review, or a task that ended without releasing its edits.
- **Changes a second brain rejected**: review.completed with approve false.
- **Experiments run**: Rows in the experiments table: baseline against candidate, verdict computed from numbers.

## Memory

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Conclusions stored | 183 | 208 | 622 | - | — |
| Conclusions read back | 50 | 46 | 125 | higher | better |
| Conclusions reinforced or contradicted | 13 | 3 | 17 | - | — |

- **Conclusions stored**: knowledge.stored events (verified conclusions with sources).
- **Conclusions read back**: Stored conclusions whose last use falls in the window: memory that was used, not only kept.
- **Conclusions reinforced or contradicted**: knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.

## Evidence

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Final answers claiming work not done | 1 | 9 | 21 | lower | better |
| False claims sent back | 7 | 9 | 16 | - | — |
| Objectives closed on words | 0 % (0/54) | 0 % (0/107) | 0.8 % (2/246) | lower | same |
| Gate verdicts GREEN | 95.5 % (21/22) | 34.8 % (8/23) | 66 % (31/47) | higher | better |
| Guards that held | 48 | 59 | 110 | - | — |

- **Final answers claiming work not done**: Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.
- **False claims sent back**: claim.rejected: a final answer claimed work its task did not do and was sent back to be rewritten (journaled since M3).
- **Objectives closed on words**: Objectives closed DONE whose check was only task_success.
- **Gate verdicts GREEN**: Journaled verifications that were GREEN.
- **Guards that held**: Releases refused for touching a judge or an existing test, and calls refused by the permission gate.

## Demonstration

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Days since the capability matrix was generated | 5 | — | 5 | lower | — |

- **Days since the capability matrix was generated**: Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.
