# SYRAX rise ledger

Generated 2026-10-26 12:20 by `python -m syrax.rise` at commit `ce024ca` from the journal (53558 events, 2026-09-30 15:18 to 2026-10-26 12:20). Every number is a read-only query over the journal; nothing here is typed by hand. **Last** is the last 7 days, **previous** the 7 days before, **trend** compares the two in the metric's own better direction. A dash means there is no evidence, which is reported as such.

The milestones in [EXECUTION_PLAN.md](EXECUTION_PLAN.md) are judged by these numbers.

## Brain

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Quality suite pass rate | 97 % (run #85, 67 cases) | 98 % (run #51, 51 cases) | 97 % (run #85, 67 cases) | higher | worse |
| Machine-checked objectives done | 96.4 % (27/28) | 97.2 % (103/106) | 98.5 % (255/259) | higher | worse |
| Attempts per objective done | 1 (median of 27) | 1 (median of 103) | 1 (median of 255) | lower | same |
| Objectives that repeated a failed strategy | 0 % (0/13) | 29.3 % (12/41) | 17.1 % (13/76) | lower | better |
| Brain calls per verified objective (median) | 4 (median of 27) | 4 (median of 103) | 4 (median of 240, 15 closed without a task) | lower | same |
| Minutes per verified objective (median) | 0.4 (median of 27) | 0.4 (median of 103) | 0.3 (median of 240, 15 closed without a task) | lower | same |
| Tool calls that failed | 7.7 % (87/1127) | 15.3 % (397/2603) | 11.9 % (624/5260) | lower | better |
| Own tasks left unfinished | 2.8 % (1/36) | 13.9 % (28/201) | 9 % (38/423) | lower | better |
| Quality runs that regressed | 0 % (0/34) | 19.2 % (5/26) | 10.6 % (9/85) | lower | better |

- **Quality suite pass rate**: Latest full quality run (at least 10 cases) in the window: real tasks through the real brains, judged by checks on disk and in the journal.
- **Machine-checked objectives done**: Objectives closed in the window whose check is evidence (not task_success): DONE out of DONE + BLOCKED.
- **Attempts per objective done**: Median attempts of the machine-checked objectives closed DONE in the window.
- **Objectives that repeated a failed strategy**: Objectives with two or more attempts, updated in the window, whose attempts_log holds two attempts that were not DONE and used the same strategy fingerprint (the distinct tool calls of the attempt, as autonomy records them), out of all objectives with two or more attempts.
- **Brain calls per verified objective (median)**: Median over the machine-checked objectives closed DONE in the window of the brain.answered events of all their tasks (every attempt, from attempts_log, evidence.task_id and last_task_id); objectives closed without a task are left out and counted in the detail.
- **Minutes per verified objective (median)**: Median over the same objectives of the wall time of all their tasks, each from its start to the event that ended it (completed, failed, cancelled or interrupted; its last update when none did).
- **Tool calls that failed**: tool.failed out of all finished tool calls in the window (refusals by a guard count as failures).
- **Own tasks left unfinished**: Autonomous tasks that ended PARTIAL (step limit, loop stop) or FAILED, out of all finished ones.
- **Quality runs that regressed**: Quality runs in the window (full suite or a subset re-run) whose status was REGRESSION: a pass rate below the run they were compared to, out of all quality runs.

## Evolution

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Commits SYRAX made to itself | 6 | 15 | 24 | higher | worse |
| Commits that only regenerated docs | 2 | 3 | 7 | - | — |
| Releases that landed | 50 % (8/16) | 23.1 % (18/78) | 26.5 % (31/117) | higher | better |
| Own edits in the running tree | 0 | 2 | 52 | lower | better |
| Changes rolled back by the gate or the review | 1 | 8 | 17 | lower | better |
| Unreleased edits cleaned up after a task | 29 | 72 | 115 | lower | better |
| Changes a second brain rejected | 1 | 1 | 2 | - | — |
| Experiments run | 16 | 70 | 104 | higher | worse |
| Human interventions | 15 | 57 | 93 | lower | better |

- **Commits SYRAX made to itself**: commit.created that changed a file outside docs/: code, tests or config that passed the gate and a second brain's review and was committed by SYRAX's release. The daily regeneration of the docs is counted apart.
- **Commits that only regenerated docs**: commit.created whose files are all under docs/: the daily publish of the ledger, the devlog, the archive and the capability matrix through the same gate and review, with no code changed.
- **Releases that landed**: commit.created out of release attempts in the window: gate runs (verification.completed; every release that reaches the gate runs it once, the daily ledger publish included, which releases without a tool call) plus release calls refused before the gate (tool.failed).
- **Own edits in the running tree**: Editor edits by SYRAX's own tasks that landed in the running tree instead of the task's isolated worktree (M1; every edit before it counts).
- **Changes rolled back by the gate or the review**: rollback.created by a release: the gate was BLOCKED, a second brain rejected the change, or no second brain could review it (any reason but the end-of-task cleanup).
- **Unreleased edits cleaned up after a task**: rollback.created with reason "task ended without a committed release": a task left edits it never released (step limit, failure, cancel) and they were restored or kept as a diff; no verdict on the change.
- **Changes a second brain rejected**: review.completed with approve false.
- **Experiments run**: Rows in the experiments table: baseline against candidate, verdict computed from numbers.
- **Human interventions**: Times a person had to step in: ask events (SYRAX asked a question), permission.authorized with authorized_by human, objective.* events whose note a human wrote ("human: ...", a dismissal), and task.cancelled by a human (aborted, removed from the queue or dismissed).

## Memory

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Conclusions stored | 114 | 234 | 680 | - | — |
| Conclusions read back | 18 | 44 | 125 | higher | worse |
| Conclusions reinforced or contradicted | 14 | 8 | 24 | - | — |

- **Conclusions stored**: knowledge.stored events (verified conclusions with sources).
- **Conclusions read back**: Stored conclusions whose last use falls in the window: memory that was used, not only kept.
- **Conclusions reinforced or contradicted**: knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.

## Evidence

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Final answers claiming work not done | 0 | 1 | 21 | lower | better |
| False claims sent back | 4 | 14 | 20 | - | — |
| Objectives closed on words | 0 % (0/27) | 0 % (0/103) | 0.8 % (2/257) | lower | same |
| Gate verdicts GREEN | 100 % (9/9) | 75 % (21/28) | 69.2 % (36/52) | higher | better |
| Guards that held | 25 | 82 | 125 | - | — |
| Interrupted tasks resumed or dismissed | 100 % (1/1) | 100 % (3/3) | 100 % (10/10) | higher | same |

- **Final answers claiming work not done**: Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.
- **False claims sent back**: claim.rejected: a final answer claimed work its task did not do and was sent back to be rewritten (journaled since M3).
- **Objectives closed on words**: Objectives closed DONE whose check was only task_success.
- **Gate verdicts GREEN**: Journaled verifications that were GREEN.
- **Guards that held**: Releases refused for touching a judge or an existing test, and calls refused by the permission gate.
- **Interrupted tasks resumed or dismissed**: Tasks marked task.interrupted in the window (a crash or restart cut them) that have since reached a terminal status: resumed and finished, failed, or dismissed by a human (task.cancelled), out of all tasks interrupted in the window.

## Demonstration

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Days since the capability matrix was generated | 1 | — | 1 | lower | — |

- **Days since the capability matrix was generated**: Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.
