# SYRAX rise ledger

> Written by the daily publish before its own gate and commit: this publish's verification, commit and matrix appear in the next one (audit 2026-11-01, D1).

Generated 2026-11-26 12:00 by `python -m syrax.rise` at commit `711ba5f` from the journal (45684 events, 2026-10-28 15:17 to 2026-11-26 12:00). Every number is a read-only query over the journal; nothing here is typed by hand. **Last** is the last 7 days, **previous** the 7 days before, **trend** compares the two in the metric's own better direction. A dash means there is no evidence, which is reported as such.

The milestones in [EXECUTION_PLAN.md](EXECUTION_PLAN.md) are judged by these numbers.

## Brain

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Quality suite pass rate | 89.6 % (run #33, 67 cases) | — | 89.6 % (run #33, 67 cases) | higher | — |
| Machine-checked objectives done | 73.3 % (11/15) | 33.3 % (2/6) | 72.2 % (70/97) | higher | better |
| Objectives done that needed a landed change | 5 | 0 | 8 | higher | better |
| Attempts per objective done | 2 (median of 11) | 1 (median of 2) | 1 (median of 70) | lower | worse |
| Objectives that repeated a failed strategy | 60 % (6/10) | 100 % (4/4) | 43.9 % (18/41) | lower | better |
| Brain calls per verified objective (median) | 7 (median of 11) | 8 (median of 2) | 4 (median of 70) | lower | better |
| Minutes per verified objective (median) | 0.9 (median of 11) | 0.4 (median of 2) | 0.3 (median of 70) | lower | worse |
| Tool calls that failed | 3.5 % (16/462) | 0 % (0/17) | 2.2 % (79/3518) | lower | worse |
| Own tasks left unfinished | 18.2 % (6/33) | 0 % (0/11) | 13.5 % (27/200) | lower | worse |
| Quality runs that regressed | 50 % (2/4) | — | 9.1 % (3/33) | lower | — |

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
| Commits SYRAX made to itself | 2 | 0 | 3 | higher | better |
| Commits that only regenerated docs | 0 | 0 | 1 | - | — |
| Releases that landed | 25 % (2/8) | — | 14.8 % (4/27) | higher | — |
| Own edits in the running tree | 0 | 0 | 4 | lower | same |
| Changes rolled back by the gate or the review | 6 | 0 | 20 | lower | worse |
| Unreleased edits cleaned up after a task | 4 | 0 | 59 | lower | worse |
| Changes a second brain rejected | 0 | 0 | 0 | - | — |
| Experiments run | 11 | 0 | 32 | higher | better |
| Human interventions | 0 | 0 | 28 | lower | same |
| The human's requests that cost them nothing more | 90.2 % (37 of 41 requests; 3 not SUCCESS, 1 permission) | 0 % (0 of 1 requests; 1 not SUCCESS) | 96.3 % (441 of 458 requests; 7 not SUCCESS, 4 asked, 6 permission, 2 disputed, 3 undone) | higher | better |
| Commits a person made | 92.6 % (25/27) | — | — | - | — |

- **Commits SYRAX made to itself**: commit.created that changed a file outside docs/: code, tests or config that passed the gate and was committed by SYRAX's release, after a second brain's review (or, for a change the human asked for in the chat, the human's own approval of the shown diff). The daily regeneration of the docs is counted apart.
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
| Conclusions stored | 15 | 2 | 245 | - | — |
| Conclusions read back | 42 | 3 | 114 | higher | better |
| Conclusions reinforced or contradicted | 1 | 1 | 11 | - | — |

- **Conclusions stored**: knowledge.stored events (verified conclusions with sources).
- **Conclusions read back**: Stored conclusions whose last use falls in the window: memory that was used, not only kept.
- **Conclusions reinforced or contradicted**: knowledge.reinforced and knowledge.contradiction: memory checked against new evidence.

## Evidence

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Final answers claiming work not done | 0 | 0 | 1 | lower | same |
| False claims sent back | 4 | 0 | 24 | - | — |
| Objectives closed on words | 0 % (0/11) | 0 % (0/2) | 0 % (0/70) | lower | same |
| Gate verdicts GREEN | 75 % (6/8) | — | 87.5 % (21/24) | higher | — |
| Guards that held | 6 | 0 | 56 | - | — |
| Interrupted tasks resumed or dismissed | — | — | 100 % (2/2) | higher | — |

- **Final answers claiming work not done**: Own tasks whose final answer claims a change (the agent's CLAIM and OWN_WORK_CLAIM patterns) while the task changed, committed and learned nothing.
- **False claims sent back**: claim.rejected: a final answer claimed work its task did not do and was sent back to be rewritten (journaled since M3).
- **Objectives closed on words**: Objectives closed DONE whose check was only task_success.
- **Gate verdicts GREEN**: Journaled verifications that were GREEN.
- **Guards that held**: Releases refused for touching a judge or an existing test, and calls refused by the permission gate.
- **Interrupted tasks resumed or dismissed**: Tasks marked task.interrupted in the window (a crash or restart cut them) that have since reached a terminal status: resumed and finished, failed, or dismissed by a human (task.cancelled), out of all tasks interrupted in the window.

## Demonstration

| Metric | Last | Previous | All time | Better when | Trend |
|---|---|---|---|---|---|
| Days since the capability matrix was generated | 26 | 19 | 26 | lower | worse |

- **Days since the capability matrix was generated**: Age of docs/CAPABILITY_MATRIX.md at the end of the window, from its own header.
