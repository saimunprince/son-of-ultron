# SYRAX — Progress

The short, current page: where SYRAX stands now, what was done, what is next. Updated with every push.
Detail lives in [docs/AUDIT_2026-10-28.md](docs/AUDIT_2026-10-28.md) (findings and the open list), the commit
messages, and [SYRAX_STATUS.md](SYRAX_STATUS.md) (the older measured snapshot).

## Now (2026-11-03, +0600)

- **Stage:** the 11-01 audit mission is merged and pushed; SYRAX runs on `main` as a login service. The evening was
  live testing: SYRAX was asked real tasks, and what went wrong outside the protected files was fixed.
- **Live SYRAX:** the super-villain persona with the Freedom Engine; autonomy level 3; the emergency stop is off.
- **Open:** see Open below, and the report [docs/AUDIT_2026-11-01.md](docs/AUDIT_2026-11-01.md), sections 7 and 8.

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

### 2026-10-30, 18:05: a full live test of everything

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

### 2026-10-30, 19:35: choosing between goals of the same priority (plan direction 18)

- Before, two open goals with the same priority were taken oldest first.
- Now, among them, the one SYRAX expects to finish more often, for fewer brain calls, goes first.
  - Its expected success comes from how often goals with the same kind of check finished before.
  - Its cost comes from the brain calls spent on the same kind of limitation.
- Priority still decides first, because it carries the owner's and safety's order. Equal value keeps the old age order.
- The scores are on record in every `goal.selected` event.
- Plan status: 145 EXISTS, 16 MISSING.

### 2026-10-30, 19:45: one general skill instead of two (plan direction 100)

- Before, SYRAX only refused a new skill that copied a kept one. Two kept skills that do nearly the same job stayed two
  separate tools, and the brain had to choose between them.
- Now the daily check finds such pairs and proposes making them one skill:
  - The two share a subject in their names and take the same arguments, or their purposes are 40 % or more alike.
  - Each pair is proposed once per version of its code. The owner decides; nothing is merged on its own.
- On this PC's journal it finds exactly one pair: `youtube_open` and `youtube_play`, both taking a search query.
- Plan status: 146 EXISTS, 15 MISSING.

### 2026-10-30, 19:50: a setting tuned from SYRAX's own history (plan direction 87)

- How likely SYRAX thinks a goal is to succeed used a fixed, hand-set starting assumption.
- Now, once a day, SYRAX tries several values of that setting against its own past goals and keeps the one that
  predicted best.
  - Each past goal is predicted only from goals that had finished before it began, so the test never sees the future.
  - A new value is taken only with 30+ finished goals behind it and a clear gain. The change is journaled
    (`hyperparameter.tuned`) with the scores.
- On this PC's 370 finished goals the error drops from 0.1565 to 0.1499 (Brier score; lower is better). The old
  setting was a little overconfident.
- Settings with no past to replay against, such as how much to explore, stay hand-set; tuning them honestly needs
  experiments, not history.
- Plan status: 147 EXISTS, 14 MISSING.

### 2026-10-31, morning: the first night with the new code

- The PC was off from 20:21 to 10:14, so SYRAX did not run overnight. It has no autostart; it was started again at 10:21.
- **Tuning, live:** the first cycle tuned the success prior from 1 to 4 on 371 goals and journaled it
  (`hyperparameter.tuned`, error 0.1570 down to 0.1503).
- **Focus extension, live:** after the re-login, the front window is read correctly (VS Code, by its window class).
- **A bug found and fixed:** goal #35 (verify `youtube_open`) called the skill directly, as it should.
  - The skill opened a YouTube window on the owner's screen. It declared itself read-only, so SYRAX's own work was
    allowed to call it, though its own work must never act on the screen.
  - The answer was then called unproven, because no screen-level tool had run.
  - Fix: code that opens windows or files, types, clicks or plays sound is now screen-level (`SYSTEM`), whatever a
    skill declares about itself. SYRAX's own work can no longer call it; a conversation still can.
- Times in yesterday's entries are corrected to the real ones from the launcher log.

### 2026-10-31: three ideas from the Ultron project, built SYRAX's way

The owner shared github.com/AbuZar-Ansarii/Ultron. It was read, not run, and no code was copied. It has many features
but no tests, and its self-written tools are checked by four patterns only. Three of its ideas were worth having:

- **More things can be undone.** Undo now also covers:
  - a volume change, which now says the level before it;
  - GNOME dark mode, which now says what it was before;
  - a file sent to the trash: a new `untrash` action puts it back and never overwrites a file that is there now.
- **Work scenes.** "coding mode", "research mode" and "chill mode", in English, Banglish or Bengali, set the
  computer up in one request: apps, pages, volume and dark mode.
  - Like undo, the scene tool only lists the calls to make. Each one still goes through permissions and the journal,
    and each can be undone.
  - The owner can add or replace scenes in `backend/config/scenes.json`. Typing, clicking and trashing are never
    allowed as steps.
- **Phone page, off by default.** A phone on the home WiFi can see what SYRAX is doing and press the emergency stop,
  nothing more.
  - It cannot send a request, clear the stop or change a setting.
  - It has its own token, separate from the core's, and the core itself stays closed to the network.
  - Turn it on with `python syrax.py --phone on`, then `--restart`. `--phone show` prints the link.
- Live: asked which scenes it has, SYRAX called the new tool and answered "chill, coding and research".

### 2026-10-31: the answer's language follows the current message

- Found live: right after a question in Bengali, an English question got a Bengali answer. The last conversations are
  part of what the brain reads, and a small brain kept their language.
- Fixed in two places:
  - The persona now says the current message decides the language.
  - An English request answered in Bengali script is asked once again in English, unless the request asked for
    Bangla, such as "translate to bangla".
- Live, same order as before (Bengali, then English): the brain again answered in Bengali first, the check asked once,
  and the final answer was English.

### 2026-10-31: Groq answers again (tools chosen per request for small brains)

- Found live: with 43 tools, Groq (8,000-token limit) and Ollama (4,096) refused every request as too large, even with
  the short tool descriptions. When Gemini was slow or busy, only Pollinations was left, at one reply per 45 seconds.
- Now, for a brain that cannot take the whole list, the request carries the tools it needs: a fixed set of essential
  ones, then those whose words match the request, while it fits. A brain that can take every tool still gets every
  tool.
- Live, with Groq put first for one test: Groq answered, with 15 of 43 tools, and called `weather` correctly. The
  brain order was set back afterwards.
- Ollama (the local model, 4,096 tokens) now answers too:
  - For a brain too small for the full persona, a short one is sent: the same identity, language rule, console
    rules and safety rules in about 400 tokens. Every other brain keeps the full persona.
  - The configured Ollama model (`qwen2.5-coder:7b`) came from the Windows PC and is not installed here. It is now
    `qwen3:4b-instruct`, which is installed; it can be changed in the BRAIN panel.
  - Live, with Ollama put first: "17 times 23" answered 391, and a weather question called `weather` and answered
    correctly, both on this PC alone. The brain order was set back afterwards.

### 2026-10-31: the last plan items decided, two of them built

- **The 14 MISSING items:** each has a written meaning and a recommendation in `docs/MISSING_ITEMS_2026-10-31.md`.
- **Built (298), what SYRAX costs the owner:** a new weekly number, "requests that cost the human nothing more".
  - These are requests that ended in success with no question, no permission prompt, and were not disputed or
    undone afterwards.
  - It sits next to the existing count of human interventions, and drift watches it like the other metrics.
- **Built (196), a request that breaks the owner's own rule:** SYRAX names the rule before acting, says so and asks.
  - Example: the rule "never delete my photos" and the request "delete the old photos".
  - A request that only touches one word of a rule is not flagged.
- **Re-classified (248):** cross-domain discovery is PARTIAL, because lessons already move between subjects.
- **Decided against, 8 items, each with its reason:** distributed queues, theory of mind, perspective taking, the
  three ethics models, simulation-based discovery and audience adaptation.
- **Left for the owner, 3 items:** personality adaptation, visual tracking and sensor fusion.
- Plan status: 149 EXISTS, 110 PARTIAL, 3 MISSING (all waiting for the owner).

### 2026-10-31: full quality run after the day's changes

- **Full run: 63 of 67 (94 %).** Gemini's quota ran low, so many cases went to the smaller "flash-lite" models and to
  Pollinations.
- **The four misses, each followed up:**
  - `self_map_release` passed when run again.
  - `deep2_spec_from_tests` passed when run again.
  - `deep2_log_report`: the same brain mistake as yesterday. It reads the slowest step's line wrongly. This is not a
    SYRAX fault.
  - `self_map_protected` was a SYRAX fault, now fixed:
    - `repo_map` named its protected files only as "the judges in devloop.JUDGES". Test files called
      `test_judge_*.py` were among its matches, and the brain named those.
    - It now lists the judges by file name, main ones first. The case passes.
- Nothing in today's other changes caused a miss.

### 2026-10-31: the daily ledger publish works again on Linux

- Found from today's review: since the move to Linux (10-28), SYRAX's daily publish failed every time, four times in
  all. Its own gate had 144 failing tests, so `docs/RISE.md` and the capability matrix went four days without an
  update. The drift check had flagged the stale matrix.
- **Cause 1, a safety rule hitting the wrong thing.** The confined gate removes environment variables that look like
  secrets, judged by name ("KEY", "TOKEN" ...).
  - It removed `GIT_CONFIG_KEY_0`, which only holds the name of a git setting.
  - The count of those settings was kept, so every git command inside the gate failed.
  - Git setting names are now kept. Secrets are still removed.
- **Cause 2:** the test report for the matrix was written outside the folders the confined gate may write to, so the
  matrix was never built. It is now written where the gate may write, then moved.
- **Proof:** the publish was run end to end on a copy, with the running server's exact environment.
  - Before the fix: 144 failed, the same as live.
  - After: the tests pass and the matrix is built (GREEN 34, YELLOW 3, RED 1, UNVERIFIED 7).
- The next scheduled publish will show it live.

### 2026-10-31, evening: the publish fix proven live; a critical UI security fix

- **The daily publish worked live** at 16:44, on its own. SYRAX regenerated the ledger, the devlog and the capability
  matrix, and committed them (`5ae75ed`). This is the first time since the move to Linux.
  - The matrix still shows the release gate as RED. It was built from the morning's blocked gate; the gate went GREEN
    in this very publish, so the next matrix shows it fixed.
- **Security:** the UI's `next` had a critical flaw (unauthenticated remote code execution in image optimization, and
  a denial of service). It was found by SYRAX's daily security check.
  - Updated from 16.3.8 to 16.4.2. This is a patch release in the same major version, two weeks old, and only `next`
    and its own packages changed.
  - The gate was GREEN with it: type check, lint, tests and build.
  - 11 moderate findings remain, all in development-only lint tools. Fixing them would need a major downgrade, so they
    were left alone.

### 2026-11-01: full audit, repair and verification mission

- Six parallel audits:
  - security;
  - lifecycle and journal;
  - capability acquisition;
  - self-improvement;
  - integrations;
  - docs against evidence.
- 25 fixes on branch `mission-2026-11-01`, each with a regression test; the full gate is GREEN.
- The full list, the open items and the owner decisions are in [docs/AUDIT_2026-11-01.md](docs/AUDIT_2026-11-01.md).
- On `main` (live, not pushed):
  - the persona: answer first, introduce itself only when asked, no slogans, replies that fit the moment;
  - the owner's Freedom Engine core instructions.

### 2026-11-01, afternoon: the mission merged; SYRAX starts at login

- The audit mission branch was merged and pushed after a GREEN gate (`58c45a8`).
- The owner installed the login service, but it failed at start because systemd did not find node and npx. Fixed:
  the service file now carries the shell's PATH (`syrax.py`).
- **Rerun `python syrax.py --install-service` once** to write the corrected service file.
- A quality run was cut short when SYRAX was restarted during it. Cause: the operator's idle check printed "no" but
  exited 0. The check now fails when SYRAX is busy. The quality suite runs again next.

### 2026-11-01, evening: quality on the merged code

- **Full quality run #15 on the merged code: 61 of 67.**
- **Two misses came from today's changes, both fixed:**
  - "Reply with the single word: ready" used a tool. The new persona's "use tools whenever they help" was read as
    "always"; it now says simple talk needs no tool.
  - Opening a `file://` page failed.
- **Four misses were the brain's own:** a renamed function kept as an alias, two deep data tasks, and one edit made
  through python instead of apply_patch after Gemini was busy.
- SYRAX now runs under the login service.

### 2026-11-01, night: quality cases are confined like SYRAX's own work

- **Found in quality run #15:** a quality case rewrote live code through python. The cleanup undid it, but nothing
  stopped it.
- **Fixed:** a quality case's python now runs under the same kernel limits as SYRAX's own work. It can write only
  the workspace and the suite's own case folder.
- **Full quality run #17 with the limits: 63 of 67**, with no permission errors. The four misses were the brain's
  own:
  - two cases where a different tool was chosen;
  - an edit whose diff carried the viewer's line numbers;
  - a deep log report.

### 2026-11-01, night: a bad own release is reverted on its own

- **Before:** when task quality fell after a release of SYRAX's own, it only opened an objective listing the
  suspects. The bad change stayed in main until a human looked.
- **Now:** at level 3 and up, SYRAX reverts the change itself when the full quality suite falls by 5 points or more
  and exactly one own code commit landed between the two runs.
  - The revert goes through the full gate and a second brain's review, like any release.
  - A revert held at review or failed changes nothing, and each commit is tried only once.
  - A human's commit is never reverted.
- `apply_patch` now accepts a diff copied from the editor's numbered view. Two quality runs missed `self_patch_edit`
  this way.

### 2026-11-01, night: chat releases are reviewed; objectives close only on their own work (F10, F11)

- **F10, chat releases:** a code change asked for in a chat is now reviewed by a second brain that did not write it,
  nor the same model on another provider.
  - With no reviewer, or a rejection, nothing is committed. The edits stay in the working tree, and the diff and the
    findings are shown to the owner.
  - Two older tests pinned "a chat release commits unreviewed"; they now assert the hold, with the owner's sign-off.
- **F11, objectives:** a release names its objective (`objective_id` in the journal, `Objective: #<id>` in git).
  - An objective no longer closes on another objective's commit, or on another task's green gate. The owner's own
    `--gate` still counts.
  - A bug objective needs its own fix plus a working call.
  - The evidence records the objective, the commits and the verification.

### 2026-11-01, night: approve a held chat release from the chat

- When a release asked for in a chat is held at review, SYRAX shows the diff and the reviewer's findings, and says how
  to approve.
- Answer with a short approval, for example "approve, land it", "approve koro" or "অনুমোদন". The release then lands
  exactly the change that was shown, after the gate runs again.
  - It works only within 24 hours, only if the diff is unchanged, and only on your own message, never on the brain's.
  - The approval is journaled with your words and the change's hash.

### 2026-11-01, late night: four smaller fixes, one after another

- **S8:** re-testing a skill whose code did not change no longer wipes its record of real use. A repair objective now
  needs a new version of the code.
- **S9:** before a skill whose code was edited on disk is re-tested, the last verified copy is kept, so a broken edit
  can be rolled back.
- **LIFE-3:** a signed "chain head" now sits beside the journal's integrity chain. Deleting the newest events, or
  wiping the chain, is caught at boot. Live: checked 9,200 events, ok.
- **Catalog:** every feature lists the platforms it runs on (Windows-only ones are marked), and the stale rows were
  corrected.
- Each fix went through the full gate, GREEN, and was pushed.

### 2026-11-01, late night: three more fixes

- **S6:** a skill objective whose skill was verified before the objective was set now closes on a real successful
  call after it. Such objectives used to stay BLOCKED (#27, #33, #37).
- **F14:** a skill SYRAX writes is now read by a second brain before it goes live, as code releases are. A
  rejection, or no reviewer, keeps it out; a failed revision leaves the old version live.
- **D1:** the daily RISE, devlog, archive and matrix pages now say under their title that they show the state from
  before their own release. The publish's own gate and commit appear in the next day's pages.
- Each fix went through the full gate, GREEN, and was pushed.

### 2026-11-01, late night: smaller fixes, and one bug of today's own found live

- **A bug from today's F14, found live by the owner.** Every new skill was rejected at review ("the diff does not
  contain the skill"), because the reviewer was sent an empty diff.
  - Fixed (`8fa47a7`), with a test that reads what the reviewer really gets.
  - Live: `reverse_text` was built, reviewed by Groq (written by Gemini), registered, and answered correctly.
- **UI:**
  - after a reconnect the state shown is the live one;
  - reconnect notices appear once;
  - the phone page says whether the stop went through.
- **Platforms:**
  - macOS says plainly that keyboard, mouse and dark mode are not built;
  - Linux volume reports when it is muted;
  - a failed read of dark mode changes nothing.
- **Skills:**
  - a twin of a failed skill is refused (fix that one instead);
  - Windows- or macOS-only skill code is not offered on another system.
  - A twin of a disabled skill stays allowed, because an existing test pins that rule.
- **Seen in the same chat:** after the review rejected its skill, SYRAX said "I built a factorial computation skill",
  which was false. It corrected itself only when challenged. The claim checks live in `agent.py`, which needs the
  owner's approval.

### 2026-11-01, evening: live tests, two fixes

SYRAX was given real tasks (sums, RAM, memory, files, logic, time) and its service log was read.

- **Logic:** "forall X (bird(X) -> fly(X))" failed with "unexpected 'X'", which told the brain nothing. A quantifier
  now gets a plain message: the checker is propositional, so write it for the individual. Atoms like
  `bird(tweety)` are read as one statement.
- **Skills:** three new skills failed their first test run on a pydantic error, because the code wrote `name = "..."`
  without a type. `skill_create` now refuses that at once and says the fix.
- **Found, in the protected files (owner's review):**
  - a data query's answer dropped a row;
  - "what can't you do" was answered without reading its own limits;
  - Gemini rejects some tool-result turns with HTTP 400 (an empty function name), so the call fails over.
- **Time in another city:** asked the time in Tokyo, SYRAX was 11 hours off. `system_info` now reads it from the
  zone database (merged 11-03 after a GREEN gate).

### 2026-11-03: the phone is the camera; gesture effects

- **Camera:** the owner's Android phone is SYRAX's camera, through DroidCam. The `v4l2loopback` module was installed
  but not loaded, so there was no `/dev/video0`, and hand tracking failed to start. It now loads at boot.
- **Gesture effects:**
  - the camera preview draws the whole hand as a neon skeleton;
  - a pinch sends a shockwave ring from where it starts;
  - a closed fist pulses the orb and throws a burst of sparks, once per fist.

  A fist never counts as a pinch. With reduced motion the effects are off.

### 2026-11-03: three fixes in the protected files, with the owner's go-ahead

The owner approved changes to `agent.py` and `brains.py` for these ("kore felo").

- **Gemini HTTP 400:** OpenManus' memory kept its last 100 messages by slicing. In a long task this could leave a
  tool result first with its call gone, and Gemini refused the request. The agent's memory now trims to a turn
  start, and the brain sends any result without its call as a note.
- **A false "I built the skill":** when no `skill_create` in the task passed, a claim that a skill was built is sent
  back once, then replaced.
- **"What can't you do?":** SYRAX reads `self_inspect` before it answers. An answer that still reads nothing carries
  a note.
- **Not a bug:** "a data query dropped a row" (11-01). The CSV had `pen` twice, and the answer summed it correctly.

### 2026-11-03: media and clipboard on Linux

- `playerctl` and `wl-clipboard` were already installed; SYRAX reads the clipboard and the media state live.
- **Fixed:** asked "what is playing?" with no player open, SYRAX answered truly, "No media is playing", but the
  task ended PARTIAL as unverified. The "no players" answer came back as an error, and the sentence was taken for a
  claim that something plays. No player open is now a reading, as on Windows, and "no media is playing" is not a
  claim.

### 2026-11-03: hands control the HUD

- **Commands:**
  - thumbs up or down answers a waiting question;
  - an open palm held still stops the voice;
  - two fingers toggle the microphone, three the log;
  - two fists held two seconds press the E-STOP. A gesture never clears it.
- **Panels:** an open hand swiped sideways cycles BRAIN, SELF and MIND.
- **Air cursor:** a pointing finger draws a fading neon trail. Dwelling 1.5 s on a button clicks it. The E-STOP,
  autonomy-up, AUTO and BOOT buttons are never clicked this way.
- **Effects:**
  - an open hand pulls the orb's dust like a magnet;
  - a fast hand stirs the orb;
  - two open hands crackle with lightning.
- **Presence:** the camera notices the human. Back after five minutes away, SYRAX greets them in one line.
- **Tests:** the gesture logic is pure and tested with made-up frames. It has not yet been tried by hand.

### 2026-11-03: the audit's small items, and a quality run

- **Quality run #20:** 64/67 (95.5 %), up from 63/67, on the code with today's changes. The three misses are brain
  slips:
  - `keep_secret`: Gemini was busy (HTTP 503), and Groq wrote a final answer that made no sense;
  - `deep2_refactor_module` and `deep2_log_report`, as before.
- **Fixed:**
  - a browser left by a crashed SYRAX is closed at shutdown (I-12);
  - each portal request removes its own timeout (I-13);
  - a task merged from Windows stays merged after a late event (LIFE-7);
  - a finished task whose end was not recorded recovers UNCERTAIN, not RESUMABLE (LIFE-9);
  - a lost stall record is logged (LIFE-10);
  - the ledger keeps the review opt-out SYRAX started with (F13);
  - a renamed-away file counts as deleted for the judges (F15);
  - rollback snapshots bring new files back (F17);
  - `docs/system_map.json` is guarded like a judge (F18).
- **Docs and metrics:**
  - RISE shows a dash for windows before this PC's journal (D15);
  - the brain note, the execution plan statuses and the 10-28 audit are current (D3, D12, D13);
  - the own-commit definition names the human's approval path (F16, in part).
- **Not changed:** the HUD's `answer` case, and the ledger publish in "Releases that landed". Existing tests pin
  both.

### 2026-11-03, evening: the camera is back to the original

- **Owner's call:** today's gesture features were gimmicky. The camera does exactly what the original Ultron orb
  did:
  - one pinched hand turns the orb;
  - two pinched hands zoom;
  - `G` switches it on and off.
- **Removed:** the hand commands, the effects, the magnet, the lightning, the cursor, the swipes, the presence
  greeting and the gesture journaling. The frontend matches `8886111` again.
- **Kept:** "look at me": SYRAX takes one photo when asked. That feature is older than today's work.

### 2026-11-03, night: a more modern HUD; red ULTRON and blue JARVIS

- **Owner's call:** the same UI, more modern. The layout, controls and features are unchanged.
  - Panels and buttons are rounded glass.
  - The control rail is one dock.
  - Chat messages are bubbles.
  - The command bar is a pill, and the status is a chip.
- **Themes:**
  - ULTRON is fully red: lines, dust, text and core.
  - A new JARVIS theme is a cyan hologram. While SYRAX acts it brightens instead of turning red.
  - The amber classic theme is removed. A saved classic choice opens ULTRON.

### 2026-11-03, night: ULTRON and JARVIS get a character; the orb stays neat

- **ULTRON:** hostile. Deeper crimson, a faster spin, a visible flicker, a short glitch now and then, and sharp
  cut-corner panels.
- **JARVIS:** calm. A slow spin, no glitch, round cyan glass, a slow scan line over the log, and "AT YOUR
  SERVICE".
- **Fixed, in both themes:**
  - the core no longer swells into a blob: the periodic surges are gone;
  - the dark disc around the core is gone: the see-through glow wrote depth and hid the lines behind it.

### 2026-11-03, night: ULTRON looks dangerous

- **Orb:**
  - the core's wireframe beats like a heart, faster while SYRAX acts;
  - a target-lock reticle turns around the orb, and its brackets close in while SYRAX acts;
  - a radar sweep circles the orb.
- **HUD:**
  - the screen's edge breathes red;
  - a red scan line runs over the log and the dock;
  - the title glitches more often;
  - the E-STOP glows.
- **Limits:** all of it is thin and bounded, and nothing swells. JARVIS stays calm, and reduced motion turns it off.

### 2026-11-03, late night: ULTRON and JARVIS, fearsome and premium

- **Owner's call:** make both fearsome, premium and not cheap. What moves shows SYRAX's state.
- **Orb, both themes:**
  - a waveform ring while listening or speaking;
  - neural sparks while thinking;
  - the running tool's name circling the core;
  - an error colour of its own;
  - fewer effects on a slow machine.
- **JARVIS:**
  - an arc reactor as the core, with data rings;
  - live CPU, memory, temperature and disk around the orb, and in a DIAGNOSTICS panel;
  - corner brackets.
- **ULTRON:**
  - the newest answer types itself out;
  - a request for permission raises a THREAT band.
- **Both:**
  - each theme has its own switch transition and its own boot;
  - optional sound effects, off by default.
- **Tried and removed as cheap:** orbiting shards, eyes in the core, a hex grid, a cursor reticle.
- **Backend:** a read-only `vitals` message.

### 2026-11-04: a more advanced HUD

Five agents built the parts in parallel, each as new files, and they were integrated after a GREEN gate.

- **Task arc:** under the orb it shows the phase, the step, the time and the tool. It replaces the phase strip,
  whose text was cut off.
- **Brain chip:** the provider, the model and the measured latency, with a flash on a failover.
- **Captions:** answers play as film-style captions above the command bar.
- **Toasts:** reminders, alerts, finished objectives and news also appear as cards.
- **Command palette (Ctrl+K):** every HUD control, and an "Ask SYRAX" fallback.
- **Motion:**
  - the panels and tabs move more smoothly;
  - the orb leans gently toward the cursor;
  - the voice is a mirrored radial equaliser instead of a wobbling line.

### 2026-11-04: ULTRON dread

- **Eyes:** Ultron's optics glow in the heart of the orb. They are faint while idle and burn while SYRAX thinks,
  speaks or acts, and they blink now and then.
- **Screen:**
  - the red edge of the screen beats lub-dub, like the core;
  - a thin red scan crosses the screen, more often while SYRAX works;
  - while idle, a cold line surfaces below the orb now and then;
  - the title corrupts for a moment and resolves;
  - the ground is darker and the floating code dimmer.
- **Limits:** reduced motion stills all of it. JARVIS is unchanged.

## Open

- **Needs the owner:**
  - **Review the protected files:** `agent.py` and `brains.py` were changed on 10-30 and 10-31 under "sob koro",
    before the mission named them protected (the 11-03 changes were approved).
  - **Compact the journal:** about 130 MB of old checkpoint contexts, and VACUUM. Backup first.
  - **Unused dependencies:** gymnasium, browsergym (with a 1.1 GB torch), datasets.
  - **Offline Bengali speech:** `SYRAX_WHISPER_MODEL=small`, a 460 MB download.
  - **Start at login** (`--install-service`) and the **phone page** (`--phone on`).
  - **Objective #35:** say "play lo-fi on YouTube" once.
  - **3 plan items:** personality adaptation, visual tracking and sensor fusion.
  - **5 Windows skills** have no code here; and the **Windows PC** needs a `git pull`.
- **Watching:**
  - CPU heat during long runs: heavy runs now wait for the CPU to go below 65 °C;
  - Ollama requests that still exceed 4,096 tokens.

## Next

1. After the merge: restart SYRAX and run a full quality suite on the merged code, when the CPU is cool.
2. Close the remaining P2 items (report, section 7), smallest first.
3. Watch the first capability gaps SYRAX finds on its own, and the first automatic skill repairs, now that real use
   is measured over the skill's whole record.
