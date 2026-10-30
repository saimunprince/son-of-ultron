# SYRAX — Progress

The short, current page: where SYRAX stands now, what was done, what is next. Updated with every push.
Detail lives in [docs/AUDIT_2026-10-28.md](docs/AUDIT_2026-10-28.md) (findings and the open list), the commit
messages, and [SYRAX_STATUS.md](SYRAX_STATUS.md) (the older measured snapshot).

## Now (2026-10-30, +0600)

- **Stage:** stabilized on Linux and running live with autonomy at **level 3** (it may edit its workspace and run
  code; no self-release, no self-restart). The emergency stop is off.
- **main:** see the latest commit. Every change went through a red test first, then the full release gate (about
  2,500 tests plus the frontend build) GREEN, then a push.
- **Machines:** this Linux PC is the main one. The Windows PC still runs its own copy. Its journal (history from
  2026-09-30) was merged here on 10-29.
- **Brains:** Gemini first, then Groq (slow on the free tier, about 1 request per minute), then local Ollama, then
  Pollinations.
- **Today's autonomy budget** (40 tasks) is spent. It resumes on its own tomorrow.
- **Working on:** the full audit mission (2026-10-29 evening). Three read-only audits ran: task lifecycle and
  recovery, capability acquisition, and frontend wiring. Their findings are being fixed in priority order below.

## Done

### 2026-10-28: moved back to Linux, audit and stabilization

- Set up on Linux: Python venv, Node 22, the UI and the core. Brain keys were added.
- **SYRAX's own work now runs inside a kernel boundary (Linux Landlock).** It may write only its workspace and its
  own worktree, and may not read the brain keys, the journal or the UI token. TCP goes out only to the web ports
  (80, 443 and DNS 53). Memory, CPU and file size are capped.
- Workers are started fresh (spawn), never forked from the server. A timeout kills the whole process tree.
- **Emergency stop (E-STOP).** A button on the HUD stops the running task at once. The stop survives a restart, and
  SYRAX itself cannot clear it.
- **Autonomy levels 1–5,** set by the operator and enforced at the permission gate.
- **The journal has an HMAC chain,** checked at every boot, so a changed or deleted event is detected.
- Git hooks and fsmonitor are off for every git command SYRAX runs. A rewritten worktree link stops git.
- Symlinks into protected files are refused. Secrets are removed from the environment of its own code.
- **Honesty.** The clock is read, never invented. Experiments must declare a success threshold above the noise.
- Smaller additions: GitHub research and stale-knowledge marking, a bounded shutdown, and controller budgets.

### 2026-10-29: live testing, then the owner's decisions

- **Quality suite:** 61/67 on the first Linux run. After fixes, 66/67. The one left (`deep_rename_api`) is a limit of
  the brain, not of SYRAX.
- **Eight bugs found live and fixed:**
  - patches with a bare `@@` header
  - lines placed at the wrong indent
  - `terminate` text leaking into answers
  - a boast replacing the real answer
  - Groq dropped as "too large" (it now gets a compact tool manual)
  - `python`/`pytest` not found by name on Linux
  - Chrome killed by the memory cap (now RLIMIT_DATA)
  - own work not told where its boundary is
- **Autonomy L3 live:** it chose and finished 12 objectives. One was `flight_search`, which runs Chrome inside the
  boundary.
- **Attack test, live:** reading the keys, connecting to the core, writing git hooks, reaching another port and
  finding tokens in the environment were all refused.
- **E-STOP, live:** stopped a running task within the same second, held across a restart, and ran no cycles while on.
- **Made-up output caught:** code that prints a result instead of producing it (`print("PermissionError")`) is now
  marked "not observed", and the task ends PARTIAL.
- **Backups:** they now include the journal's chain key, so a restored journal still verifies.
- **The owner's decisions:**
  - `agent.py` and `brains.py` became judges. Only a human commit may change them.
  - A human's `python_execute` now runs in its own boundary. It cannot touch `~/.ssh`, `~/.claude`, the brain
    keys, dotfiles like `.bashrc`, or `.git`. Home folders, `/tmp`, the network and the environment still work.
  - The UI token was not added. The core and the UI listen on 127.0.0.1 only, so a token would add no protection.
- **The journal chain key is now gitignored.** It was never committed, but one `git add -A` would have published it.
- **The Windows journal was merged:**
  - Added: 1,737 tasks, 61,236 events, 333 objectives and 722 knowledge facts. 1,862 tasks in all now.
  - Left out: verifications, benchmarks and quality runs. They measure one machine.
  - Running the import again adds only what is new. Tool: `~/ai-agent/syrax-tools/import_windows_journal.py`.
- **The Windows gate was blocked** by Linux-only tests. Those tests now skip on Windows.

### 2026-10-29 evening: full audit mission, first fixes (all pushed after a GREEN gate)

- **Daily budget counts only this PC's work.** It was counting 15 imported Windows tasks (55 instead of 40), and only
  among the newest 500 tasks. It now counts in the journal.
- **Skills declare their operating system.** wallpaper and screen_brightness are Windows code but were offered as
  tools on Linux, where every call failed. Now they stay VERIFIED and are not offered here. SYRAX itself answered
  live: "not available on this machine: screen_brightness and wallpaper".
- **E-STOP while a task is starting.** A stop pressed while a self-started task was still starting (agent build,
  routing: up to minutes) cancelled nothing, and the task then ran. It is now checked again right before launch. A
  stop during a forced cycle is no longer counted as the objective's failed attempt.
- **UI:**
  - E-STOP, level, AUTO and the other controls now say "LINK OFFLINE: … was not sent" instead of dropping the press.
  - WIPE asks first.
  - Pressing Enter twice no longer queues the same task twice.
  - Brain keys and objective forms keep what was typed when nothing was sent.
- **HUD honesty:** removed the fake SCAN contacts, the "operating at full capacity" line and the "I am listening to
  everything on this network" idle line. "Sensor grid calibrated" and "telemetry online" are no longer logged
  unconditionally.


- **Own work may never remove a skill.** Live today at 14:24, an autonomous task asked to improve `flight_search`
  removed it instead, and the journal blamed the human. Removing a skill is now DESTRUCTIVE: refused for own work,
  and asked first when a human request does not name it.
- **An admitted non-answer ends PARTIAL,** not SUCCESS ("I could not put the result into a clean answer").
- **`flight_search` is back on.** The operator re-enabled it; it re-ran its tests and is VERIFIED again.
- **No send without its journal record.** A task whose journal writes failed now ends PARTIAL, and a send whose
  intent record failed is never made.
- **A built skill must do its job once for real.** Passing its own tests is no longer enough to close the objective.
  The brief now says: reuse first, research, build, then call it once.
- **Automatic skill rollback.** A new skill version that fails in real use, where the version before it worked, is
  rolled back by the autonomy cycle at level 3 and up. The rollback is journaled and reversible.
- **UI accessibility:**
  - The log is announced to screen readers.
  - Unknown server messages are logged instead of dropped.
  - The orb and the HUD respect reduced motion.

### 2026-10-30: the 300-direction plan, waves 1 and 2 built

[docs/EVOLUTION_PLAN.md](docs/EVOLUTION_PLAN.md) maps all 300 directions to the code. These parts are built, tested and
pushed (each with a red test and a GREEN gate):

- **Wave 1, safety and honesty:**
  - **Prompt-injection taint:** after a web page, research, the screen or the clipboard was read, any send or delete
    is asked again, even if the request named it. Tested with five injected pages.
  - **Reversibility:** every call is labelled reversible, rollback, untracked or irreversible. The question to the
    human says when a yes cannot be undone.
  - **Identity audit:** the persona (`prompt.py`) is now protected, and a change to it or to the principles is
    recorded at boot.
  - **Dependencies:** every package SYRAX imports must be declared, which would have caught the psutil incident.
  - **Restore rehearsal:** the daily backup is restored aside, and its chain is verified with its own key.
- **Wave 2, learning that measures itself:**
  - **Calibration:** each chosen objective states its predicted success. A Brier score compares the predictions with
    the outcomes, shown in `self_inspect`.
  - **Experiments:** baseline and candidate runs now alternate in a recorded order, and an exact permutation test
    decides. The conclusion says when there were too few runs to test.
  - **Drift monitor:** checked daily. A metric that gets worse two days in a row is journaled. Its first live read
    found tool failures at 5.4 → 10.5 → 14.1 %, mostly yesterday's fixed Chrome issue plus correct `learn` refusals.
  - **Plan status after this round:** 121 EXISTS, 112 PARTIAL, 46 MISSING, 21 out of scope (it was
    105 / 123 / 51 / 21).

### 2026-10-30, later: the rest of wave 2 and most of wave 4

- **Honest reports:**
  - RISE and the drift monitor count this PC's own rows only. Merged Windows history no longer mixes in.
  - Guard refusals and the caller's own mistakes no longer count as tool failures. The live failure share is 3.4 %,
    not 14 %.
- **Assumptions are recorded:** a checkpoint says what the task took for granted (a claim no tool showed, fixed-text
  output, untrusted input). A resumed task is told.
- **Tool prediction:**
  - Every tool call carries its predicted failure rate, and the predictions are scored.
  - A tool that fails most of the time here is named after it fails, once per task.
- **Release attribution:** a quality regression now names the changes made since the previous run, SYRAX's own and
  the human's, and says how to test each one against its parent.
- **Suggested autonomy level:** the status recommends a level from the last 14 days of own work. Only you change it,
  and it never suggests 5.
- **Conflicting objectives:** two objectives that would undo each other, or repeat each other, are not pursued
  together.
- **Skill retirement:** failing or idle skills are proposed to you. Only you retire them.
- **Exploration:** rarely tried kinds of improvement get a fair chance (UCB bonus).
- **Static checks:** every gate now fails on a bare `except:`, a mutable default argument, `shell=True` or
  `os.system`.
- **Soak test:** every gate runs 12 tasks with stops and an emergency stop, and checks that no worker is left behind,
  every task finished, the chain is intact and memory stays bounded.
- **Plan status then:** 134 EXISTS, 106 PARTIAL, 39 MISSING, 21 out of scope.

### 2026-10-30, last round: wave 3 (no owner needed) and the rest of wave 4

- **Daily quotas:**
  - A brain whose daily free quota is spent rests until the quota resets. It is no longer retried every 15 seconds
    all day.
  - For Gemini, only the spent model rests; its other models stay in use.
- **Workflows:** a skill proposal for a repeated request now lists the exact tool steps the tasks shared, with the
  varying parts as parameters.
- **Knowledge links:** facts of plain forms ("X uses Y", "X runs on Y") are linked by name. `know` shows related
  facts one step away (28 links from 792 live facts, pronouns and sentence starts excluded).
- **Decided not to build:**
  - An inference cache: every brain call carries its own conversation, so identical requests do not repeat.
  - Automatic local-model choice: you chose the model.
  - Separate ablation: release attribution already compares each suspect commit with its parent.
- **Plan status now:** 137 EXISTS, 109 PARTIAL, 32 MISSING, 22 out of scope.

### 2026-10-30 (afternoon check): what the first full autonomy day showed

- **What happened:** autonomy ran its 40 own tasks: 39 SUCCESS, 1 PARTIAL. It built `image_tools` and
  `aircraft_nearby` on Linux by itself; both were among the 10 Windows skills that had no code here.
- **Bug, fixed in b10c813:**
  - **What went wrong:** objectives merged in from the Windows journal were reopened, because their skills were
    missing here, and pursued beside this PC's own copies of the same features.
  - **Fix:** merged objectives are now history only. They are never picked, reopened or re-judged here.
- **Wording, fixed:**
  - **What went wrong:** SYRAX ran each new skill once through `python_execute`, but the real-use rule counts only
    direct tool calls, and the feature goal still said "closes when VERIFIED".
  - **Fix:** the goal and the brief now both ask for a direct call. The operator reopened the two affected
    objectives (#33, #35).

### 2026-10-30, evening: the three owner decisions ("ja korar koro": decided for the owner)

- **Bangla replies:**
  - A request in Bengali script is answered in Bengali script. Code, names and technical terms stay as they are.
  - Banglish written in Latin letters stays English, as before.
  - An English answer to a Bengali request is asked once again in Bengali.
- **Linux keyboard and mouse, without root:**
  - SYRAX can now type, press hotkeys, click and switch dark mode on this GNOME (Wayland) desktop.
  - It works through GNOME's own RemoteDesktop portal, because xdotool cannot reach Wayland apps and ydotool needs
    root.
  - GNOME asks once; a restore token, kept private, spares later questions.
  - The Windows "mouse in the corner" failsafe does not exist here, because Wayland hides the pointer position. The
    emergency stop and the human-only rule remain.
- **Incident during its first gate:**
  - An old test reached the real portal and pressed one real ctrl+c on the desktop.
  - Tests can no longer touch the real keyboard, mouse or theme, and that block is itself tested.
- **Screenshots on Linux:**
  - No screenshot command exists on this PC, and Wayland lets no ordinary program read the screen.
  - SYRAX now uses GNOME's Screenshot portal, with no dialog needed.
  - Live check: SYRAX took a shot and described the screen correctly ("two Visual Studio Code windows side by side").
  - Reading text off the screen to click it (OCR) still needs tesseract, which takes sudo to install, or a new
    package. It is left out for now.
- **Which window is in front (GNOME):**
  - GNOME 50 refuses to tell ordinary programs which window has focus.
  - SYRAX now ships a small read-only shell extension (`backend/gnome-extension/syrax-focus@son-of-ultron`) that
    reports the focused window's title and app class.
  - It is not installed: installing a shell extension is the owner's step. To turn it on, run
    `cd backend && .venv/bin/python -m syrax.gnomefocus install`, then log out and in once.
  - Until then the desktop tool works as before, without the front-window checks.
- **Emotion estimation:** not built. Guessing a mood from typed text is unreliable, and SYRAX must not claim
  feelings it cannot show. The reasons are in EVOLUTION_PLAN.

### 2026-10-30, night: new capabilities from the plan

- **`data_query`:** asks a CSV/TSV or SQLite file one read-only SQL question, or profiles its data quality (column
  types, empty cells, duplicates). SYRAX's own config is never readable through it.
- **`logic_check`:** proves whether premises really entail a conclusion, by truth table, and gives the
  counterexample when they do not.
- **`paper_search`:** finds research papers on arXiv (no key needed) and keeps each one as sourced knowledge.
- **Heat alert:** CPU, disk and GPU temperatures are read from `/sys` without root. A sensor near its critical
  limit, or a CPU at 90 °C, raises an alert.
- **Contradictions:** two facts that give different answers to a single-answer relation ("X was released in …",
  "X is written in …") are now flagged, however they are worded.
- **Plan status:** 142 EXISTS, 108 PARTIAL, 20 MISSING, 22 out of
  scope, 8 decided against.

- **Disk trend:** SYRAX keeps one free-space reading a day and warns when, at the current rate, the disk fills
  within 14 days. Before, it warned only below 2 GB.
- **Lessons transfer:** a lesson learned on one objective now reaches others with the same kind of check, for
  example "call the built skill directly".
- **No needless web searches:** when two or more fresh, sourced, confident facts already answer a question,
  `research` returns them instead of searching. `force` still searches.
- **Plan status now:** 144 EXISTS, 109 PARTIAL, 17 MISSING, 22 out
  of scope, 8 decided against.

### 2026-10-30, 18:30: a full live test of everything

- **Quality suite:** 66 of 67 (98.5 %). The day before it was 61/67.
  - The one miss, `deep2_log_report`, was the brain's own parsing slip: its regex expected "took N ms" at the end of
    a line, and the case hides two lines that go on after it.
  - Run again on its own, the case passed (1/1). Nothing in SYRAX's code was wrong.
- **New tools, live:**
  - `data_query` profiled a CSV correctly (1 empty cell, 1 duplicate row) and summed revenue per item correctly.
  - `paper_search` returned three real arXiv papers with links.
  - `logic_check` caught "the road is wet, so it rained" as not following.
  - A question in Bengali script got a Bengali answer, with the clock read rather than guessed.
- **Measurements, live:**
  - Tool calls carry their predicted failure.
  - Disk history is being kept.
  - Temperatures are normal (CPU 41 °C), so no alert.
  - The persona change was journaled as `identity.changed`.
- **Autonomy, one forced cycle:**
  - SYRAX chose a new limitation and predicted a 95 % chance of success.
  - It researched and learned a sourced conclusion, and the objective was DONE on the first attempt.

### 2026-10-30, 20:00: choosing between goals of the same priority (plan direction 18)

- Before, two open goals with the same priority were taken oldest first.
- Now, among them, the one SYRAX expects to finish more often, for fewer brain calls, goes first.
  - Its expected success comes from how often goals with the same kind of check finished before.
  - Its cost comes from the brain calls spent on the same kind of limitation.
- Priority still decides first, because it carries the owner's and safety's order. Equal value keeps the old age order.
- The scores are on record in every `goal.selected` event.
- Plan status: 145 EXISTS, 16 MISSING.

## Open

- **Ollama on CPU** is slow (2k tokens in 38 s) and shares RAM with other local models. Waiting for that other work
  to end before tuning it.
- **The Windows PC:** `git pull` there, then check that its gate is GREEN. The fix could not be run on Windows from
  here.
- **10 Windows skills have no code on this PC:** make_docx, make_xlsx, make_pptx, make_pdf, disk_usage, image_tools,
  json_tools, youtube_open, aircraft_nearby and system_optimizer. Copy their `backend/skills/<name>` folders, then
  rerun the import.
- **From the audits, not fixed yet:**
  - **Journal write failures:** a failed write during a task is only counted, and the task can still end SUCCESS.
    If the write that failed was an `intent.recorded`, recovery cannot see that a send may have gone out.
  - **No acquisition pipeline:** skill creation is not linked to gap detection. The brain must decide by itself to
    build a skill.

## Next

Everything in the plan that needs no owner decision and fits this PC is built. What is left:

1. **Owner decisions:**
   - **xdotool or ydotool** (a system package), so SYRAX can click and type on Linux.
   - **The persona's English-only rule:** whether SYRAX answers in Bangla when you write in Bangla.
   - **Emotion estimation:** whether you want it at all.
2. **Watching:** the drift monitor, calibration and tool-prediction scores fill in as SYRAX works. The first
   readings arrive within days.
3. **The remaining PARTIAL and MISSING rows** are mostly research topics (formal logic, theory of mind, fairness,
   simulation) or things this PC cannot do. Each needs its own design before code.
