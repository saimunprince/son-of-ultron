# SYRAX rise ledger

Generated 2026-10-31 16:36 by `python -m syrax.rise` at commit `808cf39` from the journal (12128 events, 2026-10-28 15:17 to 2026-10-31 16:36). Every number is a read-only query over the journal; nothing here is typed by hand. **Last** is the last 7 days, **previous** the 7 days before, **trend** compares the two in the metric's own better direction. A dash means there is no evidence, which is reported as such.

The milestones in [EXECUTION_PLAN.md](EXECUTION_PLAN.md) are judged by these numbers.

## Brain

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Quality suite pass rate | 94 % (run #10, 67 cases) | — | 94 % (run #10, 67 cases) | higher | — |
| Machine-checked objectives done | 76.7 % (33/43) | — | 76.7 % (33/43) | higher | — |
| Objectives done that needed a landed change | 0 | 0 | 0 | higher | same |
| Attempts per objective done | 1 (median of 33) | — | 1 (median of 33) | lower | — |
| Objectives that repeated a failed strategy | 26.7 % (4/15) | — | 26.7 % (4/15) | lower | — |
| Brain calls per verified objective (median) | 4 (median of 33) | — | 4 (median of 33) | lower | — |
| Minutes per verified objective (median) | 0.3 (median of 33) | — | 0.3 (median of 33) | lower | — |
| Tool calls that failed | 1.8 % (18/1010) | — | 1.8 % (18/1010) | lower | — |
| Own tasks left unfinished | 3.4 % (3/87) | — | 3.4 % (3/87) | lower | — |
| Quality runs that regressed | 0 % (0/13) | — | 0 % (0/13) | lower | — |

- **Quality suite pass rate**: Latest full quality run in the window (at least 10 cases and 90 % of the largest run so far; a rotation subset is not the suite): real tasks through the real brains, judged by checks on disk and in the journal.
- **Machine-checked objectives done**: Objectives closed in the window whose check is evidence (not task_success): DONE out of DONE + BLOCKED.
- **Objectives done that needed a landed change**: Objectives closed DONE in the window whose check passes only after a change landed and was measured (a release, a quality case or run, tool reliability, a repro hunt, a benchmark, a GREEN gate); research objectives are not counted.
- **Attempts per objective done**: Median attempts of the machine-checked objectives closed DONE in the window.
- **Objectives that repeated a failed strategy**: Objectives with two or more attempts, updated in the window, whose attempts_log holds two attempts that were not DONE and used the same strategy fingerprint (the distinct tool calls of the attempt, as autonomy records them), out of all objectives with two or more attempts.
- **Brain calls per verified objective (median)**: Median over the machine-checked objectives closed DONE in the window of the brain.answered events of all their tasks (every attempt, from attempts_log, evidence.task_id and last_task_id); objectives closed without a task are left out and counted in the detail.
- **Minutes per verified objective (median)**: Median over the same objectives of the wall time of all their tasks, each from its start to the event that ended it (completed, failed, cancelled or interrupted; its last update when none did).
- **Tool calls that failed**: tool.failed out of all finished tool calls in the window; calls a guard refused and calls refused for the caller's own mistake (journal.misuse) are left out. This PC's own rows only.
- **Own tasks left unfinished**: Autonomous tasks that ended PARTIAL (step limit, loop stop) or FAILED, out of all finished ones.
- **Quality runs that regressed**: Quality runs in the window (full suite or a subset re-run) whose status was REGRESSION: a pass rate below the run they were compared to, out of all quality runs.

## Evolution

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Commits SYRAX made to itself | 0 | 0 | 0 | higher | same |
| Commits that only regenerated docs | 0 | 0 | 0 | - | — |
| Releases that landed | 0 % (0/2) | — | 0 % (0/2) | higher | — |
| Own edits in the running tree | 0 | 0 | 0 | lower | same |
| Changes rolled back by the gate or the review | 1 | 0 | 1 | lower | worse |
| Unreleased edits cleaned up after a task | 15 | 0 | 15 | lower | worse |
| Changes a second brain rejected | 0 | 0 | 0 | - | — |
| Experiments run | 2 | 0 | 2 | higher | better |
| Human interventions | 7 | 0 | 7 | lower | worse |
| The human's requests that cost them nothing more | 100 % (21 of 21 requests) | — | 100 % (21 of 21 requests) | higher | — |
| Commits a person made | 98.7 % (305/309) | 63.6 % (21/33) | — | - | — |

- **Commits SYRAX made to itself**: commit.created that changed a file outside docs/: code, tests or config that passed the gate and a second brain's review and was committed by SYRAX's release. The daily regeneration of the docs is counted apart.
- **Commits that only regenerated docs**: commit.created whose files are all under docs/: the daily publish of the ledger, the devlog, the archive and the capability matrix through the same gate and review, with no code changed.
- **Releases that landed**: commit.created out of release attempts in the window: gate runs (verification.completed; every release that reaches the gate runs it once, the daily ledger publish included, which releases without a tool call) plus release calls refused before the gate (tool.failed).
- **Own edits in the running tree**: Editor edits by SYRAX's own tasks that landed in the running tree instead of the task's isolated worktree (M1; every edit before it counts).
- **Changes rolled back by the gate or the review**: rollback.created by a release: the gate was BLOCKED, a second brain rejected the change, or no second brain could review it (any reason but the end-of-task cleanup).
- **Unreleased edits cleaned up after a task**: rollback.created with reason "task ended without a committed release": a task left edits it never released (step limit, failure, cancel) and they were restored or kept as a diff; no verdict on the change.
- **Changes a second brain rejected**: review.completed with approve false.
- **Experiments run**: Rows in the experiments table: baseline against candidate, verdict computed from numbers.
- **Human interventions**: Times a person had to step in: ask events (SYRAX asked a question), permission.authorized with authorized_by human, objective.* events whose note a human wrote ("human: ...", a dismissal), and task.cancelled by a human (aborted, removed from the queue or dismissed).
- **The human's requests that cost them nothing more**: Conversation tasks that ended in the window SUCCESS, with no question asked, no permission prompted or refused, and not disputed or undone by the next request (an undo within 10 minutes), out of all that ended: what SYRAX costs the human, not only whether its tasks pass (direction 298).
- **Commits a person made**: Commits in the repository in the window by any author but SYRAX, out of all commits (git log): how much of the change still comes from people.

## Memory

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Conclusions stored | 89 | 0 | 89 | - | — |
| Conclusions read back | 15 | 0 | 15 | higher | better |
| Conclusions reinforced or contradicted | 6 | 0 | 6 | - | — |

- **Conclusions stored**: knowledge.stored events (verified conclusions with sources).
- **Conclusions read back**: Stored conclusions whose last use falls in the window: memory that was used, not only kept.
- **Conclusions reinforced or contradicted**: knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.

## Evidence

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Final answers claiming work not done | 1 | 0 | 1 | lower | worse |
| False claims sent back | 12 | 0 | 12 | - | — |
| Objectives closed on words | 0 % (0/33) | — | 0 % (0/33) | lower | — |
| Gate verdicts GREEN | 0 % (0/1) | — | 0 % (0/1) | higher | — |
| Guards that held | 17 | 0 | 17 | - | — |
| Interrupted tasks resumed or dismissed | — | — | — | higher | — |

- **Final answers claiming work not done**: Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.
- **False claims sent back**: claim.rejected: a final answer claimed work its task did not do and was sent back to be rewritten (journaled since M3).
- **Objectives closed on words**: Objectives closed DONE whose check was only task_success.
- **Gate verdicts GREEN**: Journaled verifications that were GREEN.
- **Guards that held**: Releases refused for touching a judge or an existing test, and calls refused by the permission gate.
- **Interrupted tasks resumed or dismissed**: Tasks marked task.interrupted in the window (a crash or restart cut them) that have since reached a terminal status: resumed and finished, failed, or dismissed by a human (task.cancelled), out of all tasks interrupted in the window.

## Demonstration

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Days since the capability matrix was generated | 4 | — | 4 | lower | — |

- **Days since the capability matrix was generated**: Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.
