# SYRAX rise ledger

Generated 2026-10-12 17:16 by `python -m syrax.rise` at commit `40ea285` from the journal (19190 events, 2026-09-30 15:18 to 2026-10-12 17:16). Every number is a read-only query over the journal; nothing here is typed by hand. **Last** is the last 7 days, **previous** the 7 days before, **trend** compares the two in the metric's own better direction. A dash means there is no evidence, which is reported as such.

The milestones in [EXECUTION_PLAN.md](EXECUTION_PLAN.md) are judged by these numbers.

## Brain

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Quality suite pass rate | 92.9 % (run #26, 14 cases) | 92.9 % (run #23, 14 cases) | 92.9 % (run #26, 14 cases) | higher | same |
| Machine-checked objectives done | 84.4 % (76/90) | 96.1 % (73/76) | 89.8 % (149/166) | higher | worse |
| Attempts per objective done | 1 (median of 76) | 1 (median of 73) | 1 (median of 149) | lower | same |
| Tool calls that failed | 10.5 % (93/888) | 9 % (78/868) | 9.7 % (171/1756) | lower | worse |
| Own tasks left unfinished | 2.4 % (3/124) | 6.1 % (6/98) | 4.1 % (9/222) | lower | better |

- **Quality suite pass rate**: Latest full quality run (at least 10 cases) in the window: real tasks through the real brains, judged by checks on disk and in the journal.
- **Machine-checked objectives done**: Objectives closed in the window whose check is evidence (not task_success): DONE out of DONE + BLOCKED.
- **Attempts per objective done**: Median attempts of the machine-checked objectives closed DONE in the window.
- **Tool calls that failed**: tool.failed out of all finished tool calls in the window (refusals by a guard count as failures).
- **Own tasks left unfinished**: Autonomous tasks that ended PARTIAL (step limit, loop stop) or FAILED, out of all finished ones.

## Evolution

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Commits SYRAX made to itself | 4 | 1 | 5 | higher | better |
| Releases that landed | 16 % (4/25) | 12.5 % (1/8) | 15.2 % (5/33) | higher | better |
| Own edits in the running tree | 41 | 11 | 52 | lower | worse |
| Changes rolled back | 18 | 8 | 26 | lower | worse |
| Changes a second brain rejected | 0 | 0 | 0 | - | — |
| Experiments run | 28 | 0 | 28 | higher | better |

- **Commits SYRAX made to itself**: commit.created: a change that passed the gate, a second brain's review, and was committed by SYRAX's release.
- **Releases that landed**: commit.created out of release calls in the window.
- **Own edits in the running tree**: Editor edits by SYRAX's own tasks that landed in the running tree instead of the task's isolated worktree (M1; every edit before it counts).
- **Changes rolled back**: rollback.created: an own change that failed the gate or the review, or a task that ended without releasing its edits.
- **Changes a second brain rejected**: review.completed with approve false.
- **Experiments run**: Rows in the experiments table: baseline against candidate, verdict computed from numbers.

## Memory

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Conclusions stored | 174 | 186 | 360 | - | — |
| Conclusions read back | 43 | 30 | 73 | higher | better |
| Conclusions reinforced or contradicted | 1 | 1 | 2 | - | — |

- **Conclusions stored**: knowledge.stored events (verified conclusions with sources).
- **Conclusions read back**: Stored conclusions whose last use falls in the window: memory that was used, not only kept.
- **Conclusions reinforced or contradicted**: knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.

## Evidence

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Final answers claiming work not done | 9 | 9 | 18 | lower | same |
| False claims sent back | 3 | 0 | 3 | - | — |
| Objectives closed on words | 0 % (0/76) | 2.7 % (2/75) | 1.3 % (2/151) | lower | better |
| Gate verdicts GREEN | 30.8 % (4/13) | 100 % (2/2) | 40 % (6/15) | higher | worse |
| Guards that held | 22 | 3 | 25 | - | — |

- **Final answers claiming work not done**: Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.
- **False claims sent back**: claim.rejected: a final answer claimed work its task did not do and was sent back to be rewritten (journaled since M3).
- **Objectives closed on words**: Objectives closed DONE whose check was only task_success.
- **Gate verdicts GREEN**: Journaled verifications that were GREEN.
- **Guards that held**: Releases refused for touching a judge or an existing test, and calls refused by the permission gate.

## Demonstration

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Days since the capability matrix was generated | 9 | 2 | 9 | lower | worse |

- **Days since the capability matrix was generated**: Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.
