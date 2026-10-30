# SYRAX rise ledger

Generated 2026-10-29 08:38 by `python -m syrax.rise` at commit `a310015` from the journal (5869 events, 2026-09-27 20:44 to 2026-10-29 08:38). Every number is a read-only query over the journal; nothing here is typed by hand. **Last** is the last 7 days, **previous** the 7 days before, **trend** compares the two in the metric's own better direction. A dash means there is no evidence, which is reported as such.

The milestones in [EXECUTION_PLAN.md](EXECUTION_PLAN.md) are judged by these numbers.

## Brain

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Quality suite pass rate | 100 % (run #1, 10 cases) | — | 100 % (run #1, 10 cases) | higher | — |
| Machine-checked objectives done | 83.3 % (35/42) | — | 84.6 % (44/52) | higher | — |
| Objectives done that needed a landed change | 2 | 0 | 2 | higher | better |
| Attempts per objective done | 1 (median of 35) | — | 1 (median of 44) | lower | — |
| Objectives that repeated a failed strategy | 27.3 % (3/11) | — | 25 % (3/12) | lower | — |
| Brain calls per verified objective (median) | 4 (median of 35) | — | 4 (median of 41, 3 closed without a task) | lower | — |
| Minutes per verified objective (median) | 0.7 (median of 35) | — | 0.6 (median of 41, 3 closed without a task) | lower | — |
| Tool calls that failed | 7.7 % (39/505) | — | 8.6 % (45/523) | lower | — |
| Own tasks left unfinished | 6.3 % (4/63) | — | 5.6 % (4/72) | lower | — |
| Quality runs that regressed | 0 % (0/1) | — | 0 % (0/1) | lower | — |

- **Quality suite pass rate**: Latest full quality run in the window (at least 10 cases and 90 % of the largest run so far; a rotation subset is not the suite): real tasks through the real brains, judged by checks on disk and in the journal.
- **Machine-checked objectives done**: Objectives closed in the window whose check is evidence (not task_success): DONE out of DONE + BLOCKED.
- **Objectives done that needed a landed change**: Objectives closed DONE in the window whose check passes only after a change landed and was measured (a release, a quality case or run, tool reliability, a repro hunt, a benchmark, a GREEN gate); research objectives are not counted.
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
| Commits SYRAX made to itself | 0 | 0 | 0 | higher | same |
| Commits that only regenerated docs | 0 | 0 | 0 | - | — |
| Releases that landed | 0 % (0/3) | — | 0 % (0/3) | higher | — |
| Own edits in the running tree | 0 | 0 | 0 | lower | same |
| Changes rolled back by the gate or the review | 3 | 0 | 3 | lower | worse |
| Unreleased edits cleaned up after a task | 4 | 0 | 4 | lower | worse |
| Changes a second brain rejected | 1 | 0 | 1 | - | — |
| Experiments run | 5 | 0 | 5 | higher | better |
| Human interventions | 5 | 0 | 5 | lower | worse |
| Commits a person made | 97.1 % (202/208) | 68.2 % (45/66) | — | - | — |

- **Commits SYRAX made to itself**: commit.created that changed a file outside docs/: code, tests or config that passed the gate and a second brain's review and was committed by SYRAX's release. The daily regeneration of the docs is counted apart.
- **Commits that only regenerated docs**: commit.created whose files are all under docs/: the daily publish of the ledger, the devlog, the archive and the capability matrix through the same gate and review, with no code changed.
- **Releases that landed**: commit.created out of release attempts in the window: gate runs (verification.completed; every release that reaches the gate runs it once, the daily ledger publish included, which releases without a tool call) plus release calls refused before the gate (tool.failed).
- **Own edits in the running tree**: Editor edits by SYRAX's own tasks that landed in the running tree instead of the task's isolated worktree (M1; every edit before it counts).
- **Changes rolled back by the gate or the review**: rollback.created by a release: the gate was BLOCKED, a second brain rejected the change, or no second brain could review it (any reason but the end-of-task cleanup).
- **Unreleased edits cleaned up after a task**: rollback.created with reason "task ended without a committed release": a task left edits it never released (step limit, failure, cancel) and they were restored or kept as a diff; no verdict on the change.
- **Changes a second brain rejected**: review.completed with approve false.
- **Experiments run**: Rows in the experiments table: baseline against candidate, verdict computed from numbers.
- **Human interventions**: Times a person had to step in: ask events (SYRAX asked a question), permission.authorized with authorized_by human, objective.* events whose note a human wrote ("human: ...", a dismissal), and task.cancelled by a human (aborted, removed from the queue or dismissed).
- **Commits a person made**: Commits in the repository in the window by any author but SYRAX, out of all commits (git log): how much of the change still comes from people.

## Memory

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Conclusions stored | 60 | 0 | 60 | - | — |
| Conclusions read back | 0 | 0 | 0 | higher | same |
| Conclusions reinforced or contradicted | 5 | 0 | 5 | - | — |

- **Conclusions stored**: knowledge.stored events (verified conclusions with sources).
- **Conclusions read back**: Stored conclusions whose last use falls in the window: memory that was used, not only kept.
- **Conclusions reinforced or contradicted**: knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.

## Evidence

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Final answers claiming work not done | 0 | 0 | 0 | lower | same |
| False claims sent back | 15 | 0 | 15 | - | — |
| Objectives closed on words | 0 % (0/35) | — | 0 % (0/44) | lower | — |
| Gate verdicts GREEN | 33.3 % (1/3) | — | 33.3 % (1/3) | higher | — |
| Guards that held | 13 | 0 | 13 | - | — |
| Interrupted tasks resumed or dismissed | 100 % (1/1) | — | 100 % (1/1) | higher | — |

- **Final answers claiming work not done**: Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.
- **False claims sent back**: claim.rejected: a final answer claimed work its task did not do and was sent back to be rewritten (journaled since M3).
- **Objectives closed on words**: Objectives closed DONE whose check was only task_success.
- **Gate verdicts GREEN**: Journaled verifications that were GREEN.
- **Guards that held**: Releases refused for touching a judge or an existing test, and calls refused by the permission gate.
- **Interrupted tasks resumed or dismissed**: Tasks marked task.interrupted in the window (a crash or restart cut them) that have since reached a terminal status: resumed and finished, failed, or dismissed by a human (task.cancelled), out of all tasks interrupted in the window.

## Demonstration

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Days since the capability matrix was generated | 2 | — | 2 | lower | — |

- **Days since the capability matrix was generated**: Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.
