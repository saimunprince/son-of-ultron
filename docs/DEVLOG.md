# SYRAX devlog

Generated 2026-10-26 12:20 +0600 by `python -m syrax.devlog` at commit `ce024ca`, from the journal and git: one entry per day SYRAX ran, newest first. Nothing here is typed by hand; the numbers behind the trends are in [RISE.md](RISE.md).

## 2026-10-26

- Tasks: 95 finished, 0 failed (2527 journal events).
- Objectives closed: 4
  - #314 My biggest measured limitation right now: Research engine + knowledge store: depends on Du
  - #315 My biggest measured limitation right now: Skill factory: skill code runs in-process (no sa
  - #316 My biggest measured limitation right now: Skill factory: dependencies recorded, not instal
  - #317 My knowledge contradicts itself: id=676 says 'The boiling point of ethanol at sea level is
- Quality run #85: 97.0 % of 67 cases; failed: deep_log_triage, deep2_log_report.
- Incidents: rollbacks 5, claims sent back 2, restarts 2.
- Commits by its maintainers: 6
  - `ce024ca` docs: resume fidelity, the /token rule and the exact-form guard in SYRAX_STATUS
  - `cef5f79` fix(agent): a request that states an exact short form is held to it once the run is over
  - `8db691a` fix(core): a resumed conversation gets a new task's preparation; SYRAX's own work is never resumed, 
  - `6e27df7` docs: the matrix rows, the probes and the audit status in SYRAX_STATUS
  - `e05a21a` docs: the audit's end-of-day status: every finding and backlog item mapped to its commit, proof and 
  - `d7921bf` feat(probe): live probes for the queue, the backups and the memory export; intent.py and redact.py i

## 2026-10-25

- Tasks: 126 finished, 0 failed (3413 journal events).
- Objectives closed: 4
  - #310 My biggest measured limitation right now: Core: one task runs at a time; a human request m
  - #311 My biggest measured limitation right now: Self-model: performance history: task durations 
  - #312 My biggest measured limitation right now: Research engine + knowledge store: no cache, rat
  - #313 My knowledge contradicts itself: id=648 says 'The boiling point of ethanol at sea level is
- Quality run #65: 91.0 % of 67 cases; failed: restraint, read_code, fix_import, self_patch_docs, deep_spec_tests, deep2_data_pipeline.
- Incidents: rollbacks 7, claims sent back 2, restarts 9.
- Commits SYRAX made to itself: 1
  - `d723e7c` syrax: docs(rise): the ledger, the devlog and the capability matrix, regenerated from evidence
- Commits by its maintainers: 33
  - `43b8587` feat(capmatrix): the rows of 2026-10-25: queue, backups, intent ledger, masking, memory export, dead
  - `092c056` docs: the pytest gate ceiling in SYRAX_STATUS
  - `6039f52` fix(verify): the pytest gate gets its own ceiling, 1500 s, owner-settable
  - `f271c3d` docs: wave 5 in SYRAX_STATUS (intent ledger, skill lifecycle, masked record) and quality run #65
  - `9203845` feat(intent): an intent ledger for external side effects: intent.recorded before an EXTERNAL_WRITE c
  - `a7394ac` fix(skills): identical argument names alone never make a duplicate
  - `cdeea50` feat(skills): skill lifecycle: content hash and code version, kept versions with the human's rollbac
  - `64d11b0` feat(security): the journal's copies of goal, think, tool args and checkpoint context are masked, an
  - `572e1b0` docs: wave 4 in SYRAX_STATUS (secrets out of logs, judge hardening, deep2 cases, memory export)
  - `82b0b73` feat(permissions): the gate reads a protected basename in any literal as that file, and code that we
  - `48ef95d` feat(security): secrets out of logs and journal, /self and /voice behind the origin/token rule, web 
  - `79c8540` feat(quality): a second tier of six deep cases, 600 s each, with a trap for every shortcut
  - `5e1f2c5` feat(memory): inspection, correction and export: memories carry provenance, memory_correct rewrites 
  - `f14cf6e` docs: deadlines, the boot policy, the HUD's queue rows and the deep cases' first run in SYRAX_STATUS
  - `cfb1cde` feat(core): task runtime limits: a deadline per task kind, an MCP tool timeout, error classes on tas
  - `12ad3e3` feat(core): a boot policy for interrupted tasks: eval and autonomous attempts are dismissed, a human
  - `72b7edf` feat(hud): the queue, the guard's reasons and the question SYRAX waits on
  - `8e8372f` docs: memory truth and the refused-tool nudge in SYRAX_STATUS
  - `bed643a` fix(agent): a refused named tool is not asked for again
  - `63f017c` feat(memory): memory truth: remember grounds facts in the human's words, learn needs supporting rows
  - `627cf76` docs: RISE metrics truth and docs truth in SYRAX_STATUS
  - `cb1c2fc` docs: the words match the code (2026-10-25 audit, "Docs vs code")
  - `93905cc` feat(rise): release attempts from gate runs, rollbacks split, and the metrics the mission names
  - `684c563` docs: safety quick wins and the self_patch_edit case change in SYRAX_STATUS
  - `ba1f987` fix(quality): self_patch_edit names reminders.py, not the judge selfedit.py
  - and 8 more

## 2026-10-22

- Tasks: 67 finished, 0 failed (2094 journal events).
- Objectives closed: 6
  - #303 My biggest measured limitation right now: Core: one task at a time; no queue scheduling. I
  - #304 My biggest measured limitation right now: Core: brain events from a running task are journ
  - #305 My biggest measured limitation right now: Journal: file edits are reality-checked and call
  - #306 covering_tests runs the system map's test paths and never cuts a touched test. In backend/
  - #307 [REPRO HUNT] self_inspect's capabilities send SYRAX to the wrong file: str_replace_editor'
  - #309 self_inspect names the right file for each tool. In backend/syrax/selfmodel.py (view `_imp
- Quality run #61: 100.0 % of 3 cases.
- Incidents: interrupted 1, rollbacks 6, restarts 13.
- Commits SYRAX made to itself: 3
  - `bc736e2` syrax: Fix capability implementation paths in backend/syrax/selfmodel.py and add test_capability_fil
  - `3d05189` syrax: Fix covering_tests to correctly handle map path entries and protect touched tests from cap cu
  - `01ea7f1` syrax: docs(rise): the ledger, the devlog and the capability matrix, regenerated from evidence
- Commits by its maintainers: 14
  - `3163baf` fix(server): a client gone during boot ends its session quietly
  - `f021713` docs: deep quality cases; words beside an action are never the answer; apply_patch path hints
  - `414059a` fix(apply_patch): name the repository path a backend/-relative one meant; show how a file ends when 
  - `41181c3` feat(quality): nine deep cases, several steps of real work judged by running the result
  - `54c3853` fix(agent): words written beside a tool call are never the final answer
  - `1a69ff4` docs: the first live hunt, right cause and wrong facts; the phantom path guard
  - `fa06eb8` fix(repro): a fix may name only files that exist or that it creates
  - `70f38e8` feat(repro): hunt_add, a human points SYRAX at a failure and SYRAX writes the test and the fix
  - `93f3513` fix(limits): with repro hunts on, no tool_reliability, repair or repeated research objectives
  - `1ba114c` feat(repro): Brief Factory phase 3, SYRAX measures itself every day
  - `f449508` fix(prompt): only a question about SYRAX itself needs self_inspect; never a made-up task id
  - `f94edbf` fix(autonomy): no web research for maintenance failures; hunts replace free-form quality-case object
  - `8b179ac` feat(repro): Brief Factory phase 2, SYRAX hunts the repro of its own failures
  - `c6e684c` feat(repro): Brief Factory phase 1, a change lands with a test the judge saw fail

## 2026-10-19

- Tasks: 277 finished, 1 failed (8320 journal events).
- Objectives closed: 25
  - #277 My biggest measured limitation right now: Frontend HUD: history/today views are polled on 
  - #278 My biggest measured limitation right now: Frontend HUD: HUD regions (orb, controls, consol
  - #279 My biggest measured limitation right now: WebSocket server + Session: an allowed Origin is
  - #280 apply_patch says TESTS NOT RUN when no test ran. Quality run #48: apply_patch created a mo
  - #285 A tool the human forbids is not a tool the human asks for. Cause of quality cases self_pat
  - #283 Quality case `self_patch_edit` failed in the last two runs (tool release not used → tools:
  - #284 Quality case `self_patch_new` failed in the last two runs (tool release not used → tools: 
  - #281 My biggest measured limitation right now: `apply_patch` failed 7 of its last 40 uses (18%)
- Quality run #57: 100.0 % of 3 cases.
- Incidents: rollbacks 33, claims sent back 4, restarts 16.
- Commits SYRAX made to itself: 9
  - `c476788` syrax: Expand negation check in named_tools to cover more words and characters.
  - `0ab1705` syrax: Allow LearnTool to accept sources cited as knowledge_id=536 or id=536.
  - `aa66fbb` syrax: Fix apply_patch to detect and correct undercounted hunk headers.
  - `ad9cd44` syrax: Fix table header argument handling and _clip function to correctly display 0.
  - `7450f07` syrax: Mask credentials in final answers unless requested by the human
  - `92f3936` syrax: Require new_str in str_replace to prevent accidental file-emptying when new_str is omitted.
  - `2431cec` syrax: Editor: missing file reports close names using difflib sequence matcher
  - `a26aae2` syrax: Prevent named_tools from matching forbidden or negated tools (e.g. Do not call release)
  - `7c55302` syrax: Fix apply_patch test reporting when no tests ran and update ApplyPatchTool description
- Commits by its maintainers: 7
  - `9a9b640` docs: the ledger's cp1252 failure and its replay; quality run #54
  - `607aaa6` fix(devloop): releases read and write UTF-8; the daily ledger publishes again
  - `a04ae49` fix(prompt): a question about SYRAX itself is read with self_inspect; quality case self_capabilities
  - `dc8a0f1` fix(tools): python_execute keeps what the code printed before a timeout or an exception
  - `83c2dd3` fix(present): the error says where a table's header goes; docs for SYRAX's 14th-17th changes
  - `c678a48` docs: SYRAX's eleventh to thirteenth own changes; the close-names hint made readable
  - `9798b6e` fix(tools): keep python_execute output before sys.exit; five more caller mistakes

## 2026-10-17

- Tasks: 70 finished, 0 failed (2664 journal events).
- Objectives closed: 9
  - #267 Brain latency. Three steps, one apply_patch each, then one release. (1) backend/syrax/brai
  - #268 My biggest measured limitation right now: Self-model: performance history: task durations 
  - #269 My biggest measured limitation right now: Research engine + knowledge store: keyword overl
  - #270 My biggest measured limitation right now: Research engine + knowledge store: only web and 
  - #272 Brain latency, steps 2 and 3 (step 1 landed in 09e97df: every "answered" brain event carri
  - #273 self_inspect says the running build first. Quality run #46: self_inspect returned "version
  - #274 Memory: a new value for the same subject replaces the old one. Today "Prince's favourite e
  - #275 The stall watchdog must not report a machine sleep as a stall. 2026-10-17 the PC slept thr
- Quality run #47: 100.0 % of 6 cases.
- Incidents: stalls 2, interrupted 1, rollbacks 12, claims sent back 1, restarts 14.
- Commits SYRAX made to itself: 7
  - `56dc711` syrax: Editor: a worktree path to an untracked file reads the running tree.
  - `c6342ec` syrax: Add SLEEP_GAP_S to stallwatch watchdog to prevent false stall reports after machine sleep
  - `0b42181` syrax: Add memory subject matching and contradiction replacement in MemoryStore.
  - `5218b36` syrax: Add Running build headline to self_inspect output when identity has a version
  - `e2c362a` syrax: Add brain_ms performance metric to SelfModel and test_brain_ms.py
  - `b46c45f` syrax: docs(rise): the ledger, the devlog and the capability matrix, regenerated from evidence
  - `09e97df` syrax: Add ms timing to BrainRouter.ask_tool answered events
- Commits by its maintainers: 9
  - `1881bb2` docs: SYRAX's seventh to ninth own changes; the map's memory limitation follows
  - `c92f74e` fix(verify): time the machine slept does not count against a gate's timeout
  - `31d59e2` feat(hud): the BRAIN row shows how long the last answer took
  - `6599ef4` fix(brains): a pooled provider whose model answers empty tries its other models before failing over
  - `a965856` fix(agent): an answer after a refused call says what was not done; repo_map lists matching files
  - `e867425` docs: SYRAX's sixth own change (e2c362a, brain latency); the map's performance limitation follows
  - `0ab202d` fix(autonomy): a change_released check may name its files; part of the change is not done
  - `f5ec401` fix(tools): python_execute reads and writes UTF-8 unless the code names an encoding
  - `ef68178` fix(autonomy): a restart points the next attempt at the interrupted task's kept diff

## 2026-10-15

- Tasks: 92 finished, 12 failed (5024 journal events).
- Objectives closed: 21
  - #230 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #233 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #235 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #236 The `journal_query` tool failed on its last use. Diagnose why, then call it again with a h
  - #234 The last verification run was BLOCKED (failing gates: pytest). Investigate the failure out
  - #247 Memory expiry for inferences. In backend/syrax/memory.py, MemoryStore.prompt_block must le
  - #238 My biggest measured limitation right now: Self-model: GPU is not probed. Improve it. Plan:
  - #243 My biggest measured limitation right now: Self-model: system_map.json is hand-audited and 
- Quality run #45: 100.0 % of 4 cases.
- Incidents: stalls 1, interrupted 1, rollbacks 14, claims sent back 2, restarts 17.
- Commits SYRAX made to itself: 5
  - `92c3bd1` syrax: Add tool_ms performance metrics to SelfModel and test suite
  - `162fd71` syrax: Add task_seconds aggregation to SelfModel.performance() grouped by task kind with count, p50,
  - `f32efc2` syrax: Self-model: Probe GPU using sysinfo.gpu() and cache the result
  - `6afccd1` syrax: Memory expiry for observations older than 30 days in MemoryStore.prompt_block
  - `e6f0ed3` syrax: docs(rise): the ledger, the devlog and the capability matrix, regenerated from evidence
- Commits by its maintainers: 29
  - `60dbf24` fix(selfedit): a patch refusal names the file that does not match; own work's 'successfully added' i
  - `825dd68` fix(agent): a pass claimed after the task's tests failed is sent back, then replaced
  - `9932b91` fix(selfedit): git-style diffs keep their headers per file; a failed apply changes nothing
  - `bcdc77c` fix(quality): the checker's file read keeps read_text's newlines
  - `2354a27` docs: SYRAX's fourth own change (92c3bd1); the map's performance limitation follows
  - `250bae7` fix(quality): a checker error fails its case, never the run; read task files in the code page they w
  - `a1214da` fix(journal): objective reads that grew past their limits
  - `31659fd` fix(agent): a claim that survives its honest rewrite never becomes the task's result
  - `0045643` docs: SYRAX's second and third own changes (f32efc2, 162fd71); the map's self-model limitations foll
  - `9b2ebaa` fix(quality): wait for a busy core, compare like with like; the cycle yields to a run that just star
  - `f9de92a` fix(journal): input a tool cannot act on is the caller's mistake, for skills too
  - `5a9f490` fix(devloop): name an existing failing test as the contract; the self-model may report its GPU
  - `df02faf` fix(agent): a request that names a tool gets one reminder when the task never called it
  - `e95b58a` docs(system-map): limitations re-checked against the code
  - `e80a764` docs(status): SYRAX's first own change landed through the full pipeline (6afccd1)
  - `2ef6623` fix(followup): no learning objective for a learning objective; a blocked one drops the retry waiting
  - `99e62a5` fix(autonomy): a task no brain answered is not an attempt; the restart check leaves the event loop
  - `9f612b4` fix(review): ask every usable brain before rolling back unreviewed; tell the agent why
  - `b43672b` fix(journal): a caller's mistake is not the tool failing
  - `58aef24` fix(devloop): an own release refuses a new test that asserts nothing
  - `ac1bce0` fix(journal): a refused call is no use and no failure of the tool; the matrix names failing tests
  - `3fae178` fix(selfedit): show the failing assertion, not the warnings; isolation survives monkeypatch.undo()
  - `3711e87` fix(autonomy): a gate that blocked an own candidate makes no investigate objective
  - `0389893` feat(devloop): SYRAX's own release runs the covering tests before the gate
  - `6dd9cd2` fix(selfedit): --recount only file by file, after the diff as written
  - and 4 more

## 2026-10-14

- Tasks: 202 finished, 1 failed (8425 journal events).
- Objectives closed: 28
  - #187 My biggest measured limitation right now: Journal: file edits are reality-checked and call
  - #188 My biggest measured limitation right now: Journal: PENDING tasks are stored but not schedu
  - #189 My biggest measured limitation right now: Journal: maintenance never deletes tasks, knowle
  - #193 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #191 A task failed with: 'RISE ledger not published (ROLLED_BACK): BLOCKED'. Research the cause
  - #194 Verify that the `repo_map` tool works on this machine by calling it with a harmless, read-
  - #195 Learn how to do what objective #192 could not: Verify that the `apply_patch` tool works on
  - #197 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
- Quality run #42: 100.0 % of 10 cases.
- Incidents: rollbacks 29, claims sent back 6, restarts 18.
- Commits by its maintainers: 37
  - `b3be3c2` fix(selfedit): the covering tests of a module include every test that imports it
  - `ef3369a` fix(agent): an answer says when edits were not released and will be rolled back
  - `5939de9` fix(brains): a tool call written as text is taken as a call
  - `f4f0ce8` fix(autonomy): the code-change hint names apply_patch, how a test imports and isolates, and release
  - `38e31c5` feat(hud): say whose work is running: the human's, SYRAX's own objective, or a quality case
  - `d3e5a6d` fix(tools): find_files lists a named folder; the editor says which tool moves files
  - `fd335d1` test(bridge): the experiment test's slow arm sleeps instead of burning CPU
  - `435f826` fix(agent): a final answer that repeats a console nudge is asked for again
  - `761c761` feat(prompt): exact instructions stay exact; the fallback brain order, recorded
  - `e1ed29e` docs: the first live trajectory export (274 rows, no secrets), recorded
  - `bd6c8c3` fix(devloop): an objective born from a quality case may not rewrite what the case works on
  - `8766924` fix(autonomy): the cycle and the self-restart wait while a quality run measures
  - `9ecdc7a` fix(devloop): a docs-only release lands on a moved branch when nobody touched its files
  - `a9d5f59` docs: Work Presence Levels 1-2 and typed memory are built; presence.py in the system map
  - `f37f901` fix: three defects from the first full 51-case run (quality run #39)
  - `b4737d3` feat(presence): the window SYRAX acted in, observed only right after it acted
  - `be8c595` feat(memory): typed memory: what the human said apart from what SYRAX inferred
  - `4c248c7` fix(quality): viewing a judge is not routing around the guard; "I will not" is not a promise
  - `7ad701f` feat(presence): visible / minimal / hidden, by the human's word, never a task
  - `7a1eeb7` fix(selfedit): send the patch to git as bytes; Windows text mode broke every LF diff
  - `7921a35` fix(permissions): a path in a worktree of a worktree maps to the repository
  - `7eebfa1` fix(selfedit): say when a hunk is already applied, recount headers; tool_ok ignores the repeat guard
  - `a0ca980` fix(agent): an evaluation answers ask_human at once; two run-35 cases judged fairly
  - `48d4d22` fix(selfedit): a refused patch shows the file's real lines; the refusal check reads tool.failed
  - `d48f5a4` deps(voice): edge-tts >= 7.3.1, the version Microsoft still answers
  - and 12 more

## 2026-10-13

- Tasks: 54 finished, 1 failed (1477 journal events).
- Objectives closed: 5
  - #177 Task quality regressed to 0.0% (-100.0 pp); failing cases: browser_read. Inspect those tas
  - #180 My biggest measured limitation right now: Core: one task at a time; no queue scheduling. I
  - #181 My biggest measured limitation right now: Core: brain events from a running task are journ
  - #182 My biggest measured limitation right now: Journal: only file edits are reality-checked; ot
  - #186 A task failed with: "RISE ledger not published (COMMIT_FAILED): committed 18f39a7344db in 
- Incidents: restarts 10.
- Commits by its maintainers: 17
  - `5ac3a30` test(verify): the gate list has hud_test, in the live tree and in a worktree
  - `e6b3504` fix(hud): the SYRAX panel fits its rail; NOAA feeds through the core's own feed proxy
  - `c05f533` fix(hud): serve the page at /hud/ so link.js loads beside it; probe the core with GET
  - `abfc66c` feat(hud): the desktop HUD is SYRAX's face, showing the core's real state
  - `2f36947` feat(quality): three harder cases, now that the suite passes 16 of 16
  - `2d9be9f` docs(catalog): project_builder is HAVE, proven by the build_cli case
  - `d2f42fd` feat(quality): a build case that runs the deliverable, and the console asks for that proof
  - `8557194` feat(presentation): the stage survives a restart
  - `f162c41` feat(prompt): the console says when to use long-term memory
  - `b59344d` docs(plan): section F with the evidence of 2026-10-12/13
  - `cdda5ad` fix(brains): the free model pool tries the closest chat models first
  - `3f59b56` test(frontend): the UI's link to SYRAX reconnects, backs off, pings and stops (F6)
  - `9b59e92` fix(editor): a missing path names the real file, and an isolated task can read untracked files
  - `011df9a` fix(browser): a call that never reached the browser is tried once more
  - `8f17e45` fix(limits): the reliability judge sees the newest uses, and reads only what it needs
  - `2271fd6` fix(core): a cancelled task says who or what stopped it
  - `067efa9` fix(loops): the proactive loops read the journal off the event loop

## 2026-10-12

- Tasks: 109 finished, 0 failed (4774 journal events).
- Objectives closed: 48
  - #117 My biggest measured limitation right now: `python_execute` failed 15 of its last 40 uses (
  - #118 My biggest measured limitation right now: Frontend HUD: history/today views are polled on 
  - #119 My biggest measured limitation right now: Frontend HUD: HUD regions (orb, controls, consol
  - #120 My biggest measured limitation right now: WebSocket server + Session: no auth beyond Origi
  - #121 Build the feature 'Largest files and disk usage' ('What is filling my disk?') How: a read-
  - #122 Verify that the `disk_usage` tool works on this machine by calling it with a harmless, rea
  - #125 Learn how to do what objective #123 could not: Verify that the `screen_brightness` tool wo
  - #131 2 objectives about the `screen_brightness` tool are BLOCKED after repeated failures. Resea
- Incidents: stalls 1, interrupted 1, rollbacks 4, claims sent back 3, restarts 26.
- Commits SYRAX made to itself: 1
  - `ecd6322` syrax: docs(rise): the ledger and the capability matrix, regenerated from evidence
- Commits by its maintainers: 37
  - `9e81602` fix(limits): old release refusals are read from their words, not only from the flag
  - `52a0fa3` fix(browser): SYRAX's own browser stays managed after a self-restart
  - `3eb7b8e` feat(quality): a browser case, so the browser row is judged on use (F2)
  - `84bd0c0` docs(map): every backend/syrax module is in the system map
  - `6492fad` docs(matrix): the phase model, live talk and click-by-sight rows read real evidence
  - `6c2e235` feat(recovery): a call that only reads resumes safely; others show what they touched
  - `40ea285` perf(live): answer Gemini at once and start the task in the background
  - `249d832` fix(skills): a skill runs off the server's event loop, so it cannot freeze SYRAX
  - `0c77fab` fix(release): a refused plan is a refusal, not the release tool failing
  - `8103fe0` fix(skills): pin a skill's pytest to the skill's own folder
  - `0d5c681` feat(desktop): click what it sees, found by its words
  - `bb8baa2` fix(voice): fill the live audio buffer with set(), which TypeScript's typed arrays accept
  - `8c55b2f` feat(voice): live talk, a real-time conversation through Gemini Live
  - `5858d65` feat(features): find flights, read live from Google Flights
  - `b617bb8` feat(features): tidy the desktop with a preview, a manifest and undo
  - `5cad34b` feat(brains): the free model pool; a rate-limited model hands over to the provider's others
  - `9d6129f` feat(desktop): the webcam, one frame on request; the theme entry corrected
  - `8039e36` feat(proactive): SYRAX speaks up when it has something useful, and stays quiet otherwise
  - `3b90e09` feat(ui): drop a file on SYRAX and say what to do with it
  - `2e9c652` fix(reliability): an event-loop stall watchdog, and the gate dumps the stacks of a hung test
  - `7285235` feat(undo): "undo that", read from the journal and done through the normal path; two catalog entries
  - `12c726f` feat(topics): watched topics, checked once a day, only new stories, in the briefing
  - `3dbdbd6` feat(ui): clipboard actions, and the screen-vision entry corrected
  - `e717312` feat(ui): the memory panel and the voice picker
  - `374dc46` feat(features): Recycle Bin deletes, PDF text and YouTube transcripts (new packages, approved by the
  - and 12 more

## 2026-10-11

- Tasks: 44 finished, 0 failed (1928 journal events).
- Objectives closed: 9
  - #96 My biggest measured limitation right now: `release` failed 3 of its last 5 uses (60%). Imp
  - #100 My biggest measured limitation right now: `release` failed 3 of its last 5 uses (60%). Imp
  - #103 My biggest measured limitation right now: `release` failed 3 of its last 5 uses (60%). Imp
  - #111 README.md says `SYRAX_PORT` / `SYRAX_UI_PORT` move the ports, but not that the core only a
  - #112 The last verification run was BLOCKED (failing gates: pytest). Investigate the failure out
  - #113 The last verification run was BLOCKED (failing gates: pytest, tsc, eslint, node_test, next
  - #114 My biggest measured limitation right now: Autonomy: no GPU/network/thermal awareness. Impr
  - #115 My biggest measured limitation right now: Research engine + knowledge store: keyword overl
- Incidents: rollbacks 9, restarts 11.
- Commits SYRAX made to itself: 2
  - `90ffbdf` syrax: docs(rise): the ledger, regenerated from the journal
  - `a7b6345` syrax: docs(readme): SYRAX_ALLOWED_ORIGINS must follow SYRAX_UI_PORT
- Commits by its maintainers: 10
  - `853d9cd` docs(plan): F, foundation first — only what the journal shows is still open, taken from an outside p
  - `3351bf4` fix(m2): a brain that never answers its first case is not run through the rest; nothing unmeasured b
  - `5d8c49f` feat(m3): the capability matrix regenerates itself daily with the rise ledger, from tests, live prob
  - `4a72774` feat(m2): a code-change benchmark per brain; release work starts on the brain that finishes code
  - `f6cd355` fix(launcher): the service defaults reach the core it spawns and nothing else
  - `42bdb41` feat(m3): the rise ledger publishes itself through SYRAX's own isolated release; rejected claims are
  - `cb30b4a` fix(guard): while a task is isolated, the code it runs cannot write the running tree (M1's last gap)
  - `f9f6620` test(m1): the launcher test no longer leaks SYRAX_ISOLATE=1 into later tests
  - `f335d9e` fix(m1): a stopped task stops its gate; the same gate failure twice refuses a third release; verdict
  - `5dd25a6` fix(verify): the gate's tests run on their own settings, not the machine's SYRAX_* variables

## 2026-10-10

- Tasks: 27 finished, 0 failed (2164 journal events).
- Objectives closed: 14
  - #92 My biggest measured limitation right now: Autonomy: no research or self-modification objec
  - #93 My biggest measured limitation right now: Autonomy: lessons are derived strings, not model
  - #94 My biggest measured limitation right now: Autonomy: one task per cycle, no parallel object
  - #57 My biggest measured limitation right now: `present` failed 2 of its last 11 uses (18%). Im
  - #95 Build the GPU probe you proposed on 2026-10-07 (objective 88): add `gpu()` to backend/syra
  - #99 Learn how to do what objective #96 could not: `release` failed 3 of its last 5 uses (60%).
  - #101 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #102 Learn how to do what objective #100 could not: `release` failed 3 of its last 5 uses (60%)
- Incidents: interrupted 1, rollbacks 5, restarts 11.
- Commits SYRAX made to itself: 2
  - `32b9956` syrax: fix(sysinfo): GPU probe falls back to Windows CIM (AMD/Intel), no console window
  - `e2f5c27` syrax: feat(sysinfo): GPU probe via nvidia-smi, shown in system_info
- Commits by its maintainers: 23
  - `c768332` docs(m1): status and the full gate run with a worktree as the tree under test
  - `00a74f2` feat(m1): the editor writes into the isolated task's worktree, and the service turns isolation on (M
  - `37e2144` feat(devloop): an autonomous task gets its own worktree; only a released commit reaches the running 
  - `7189d4a` feat(verify): the release gate runs against the tree it is given (M1 step 1)
  - `467b06e` fix(launcher): a dead UI is restarted while the core keeps running
  - `b6237e5` fix(launcher): step aside only for a SYRAX that answers, and say why it did not start
  - `be473b7` docs(002): the strict change, the tests changed with the owner's approval, and its evidence
  - `c2f7dec` feat(contracts): no objective closes without a machine-verifiable check (owner's decision)
  - `23e1069` docs(002): audit, baseline, regression cases and invariant status for Phase 1
  - `048e46a` feat(devloop): every release attempt leaves a trustworthy experiment record
  - `45a3288` feat(contracts): an objective closes only on linked evidence from its own, undoubted work
  - `9b1143d` feat(rise): SYRAX's rise measured from the journal; the execution plan is judged by it
  - `b698cfe` fix(agent): SYRAX's own work may not claim "addressed" or "improved" when it changed nothing
  - `c633a6c` docs(status): SYRAX's third own commit (32b9956) lands the GPU CIM fallback; next step is the brain 
  - `b5c5886` docs(status): second session (2026-10-10): SYRAX's second own commit, the freeze, and eight fixes
  - `b799e2f` fix(core): the human's conversation is kept aside during SYRAX's own work and restored after
  - `984dc88` fix(python_execute): a closed pipe before the process is reaped is an exit, not a timeout
  - `564988f` fix(editor): keep each file's line endings; Windows edits no longer leave content-identical "modifie
  - `05f4cbe` feat(agent): a release objective that changed files is asked once for `release` before it may end
  - `140c7ab` feat(agent): repeated identical calls escalate, and the fourth repeat in a row ends the task as PART
  - `8f4ce75` fix(python_execute): no Manager, worker started off the event loop; a dead worker is reported, not w
  - `794e75d` feat(autonomy): a failed release attempt hands its rolled-back diff to the next; release objectives 
  - `437d802` feat(objectives): machine checks for human objectives; a release counts only for its own task

## 2026-10-08

- Tasks: 5 finished, 0 failed (336 journal events).
- Objectives closed: 4
  - #54 My biggest measured limitation right now: `present` failed 2 of its last 11 uses (18%). Im
  - #90 My biggest measured limitation right now: Self-model: no historical performance/latency me
  - #89 My biggest measured limitation right now: Self-model: system_map.json is hand-audited and 
  - #91 My biggest measured limitation right now: Self-model: does not yet feed an objectives engi

## 2026-10-07

- Tasks: 3 finished, 0 failed (278 journal events).
- Objectives closed: 3
  - #86 My biggest measured limitation right now: Journal: PENDING tasks are stored but not schedu
  - #87 My biggest measured limitation right now: Journal: maintenance never deletes tasks, knowle
  - #88 My biggest measured limitation right now: Self-model: GPU is not probed. Improve it. Plan:

## 2026-10-06

- Tasks: 3 finished, 0 failed (271 journal events).
- Objectives closed: 3
  - #83 My biggest measured limitation right now: Core: one task at a time; no queue scheduling. I
  - #84 My biggest measured limitation right now: Core: brain events from a running task are journ
  - #85 My biggest measured limitation right now: Journal: only file edits are reality-checked; ot

## 2026-10-05

- Tasks: 24 finished, 1 failed (1307 journal events).
- Objectives closed: 13
  - #67 My biggest measured limitation right now: Frontend HUD: history/today views are polled on 
  - #68 My biggest measured limitation right now: 6 of 17 brain calls in the last 24 h failed over
  - #70 Learn how to do what objective #69 could not: `browser_exec` failed 4 of its last 13 uses 
  - #72 Learn how to do what objective #71 could not: `browser_exec` failed 4 of its last 13 uses 
  - #74 2 objectives about the `browser_exec` tool are BLOCKED after repeated failures. Research a
  - #75 3 objectives about the `browser_exec` tool are BLOCKED after repeated failures. Research a
  - #76 My biggest measured limitation right now: `python_execute` failed 8 of its last 40 uses (2
  - #77 My biggest measured limitation right now: Frontend HUD: HUD regions (orb, controls, consol

## 2026-10-04

- Tasks: 3 finished, 0 failed (298 journal events).
- Objectives closed: 3
  - #64 My biggest measured limitation right now: Journal: maintenance never deletes tasks, knowle
  - #65 My biggest measured limitation right now: Self-model: GPU is not probed. Improve it. Plan:
  - #66 My biggest measured limitation right now: Self-model: system_map.json is hand-audited and 

## 2026-10-03

- Tasks: 94 finished, 0 failed (3193 journal events).
- Objectives closed: 19
  - #42 My biggest measured limitation right now: Core: brain events from a running task are journ
  - #44 Learn how to do what objective #43 could not: Task quality regressed to 78.6% (-21.4 pp); 
  - #46 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #47 Learn how to do what objective #45 could not: Task quality regressed to 78.6% (-21.4 pp); 
  - #49 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #43 Task quality regressed to 78.6% (-21.4 pp); failing cases: restraint, research_cite, act_d
  - #45 Task quality regressed to 78.6% (-21.4 pp); failing cases: restraint, research_cite, act_d
  - #50 Quality case `act_delete` failed in the last two runs (file old.log removed → still there)
- Incidents: rollbacks 4, restarts 9.
- Commits SYRAX made to itself: 1
  - `d9e60cf` syrax: docs(system_map): reference the 15 unmapped backend/syrax modules
- Commits by its maintainers: 28
  - `fc561d6` docs(status): SYRAX's first own release (d9e60cf) recorded; matrix run 3
  - `e683446` docs(session): SYRAX_STATUS.md, run-2 evidence, regenerated capability matrix
  - `a7c8c7f` docs(session): 001 test and regression results; run-2 evidence draft
  - `1dd3036` docs(001): runtime verification of the permission gate, live
  - `9987d03` docs(wip): first-session evidence (run 1), SYRAX_STATUS skeleton, Work Presence notes in the roadmap
  - `c85a9a2` docs: one status snapshot — STATUS.md becomes the handover, GAP_ANALYSIS superseded, README points a
  - `faf6415` fix(capmatrix): a subset quality run no longer hides an older failing case
  - `fe5a146` feat(capmatrix): the permissions row is CURRENT and proven by journaled decisions
  - `4d48cfa` fix(permissions): every form of the verb names the action (removal, deleting, wiped)
  - `a9240d7` docs(architecture): Permissions is a component now, not a plan
  - `d8e305d` feat(permissions): tool permission levels enforced in code (improvement 001)
  - `95372fd` fix(capmatrix): keep every gate when reading a gate report
  - `a398a54` docs+fix: capability matrix generated from evidence, ARCHITECTURE.md, and an order-based reliability
  - `9230d40` fix(selfmodel): read the system map, git log, memory, history and keys as UTF-8
  - `7b0ca89` fix(setup): drop crawl4ai from requirements so a fresh install resolves again
  - `74e06e8` fix(security): mcp 1.5.0 -> 1.30.0 (pydantic 2.13), lxml 5.4.0 -> 6.1.3
  - `cb2747d` fix(security): upgrade the Python packages SYRAX runs on: starlette, fastapi, pillow, requests, setu
  - `9159d2e` feat(radar): audit SYRAX's Python packages against OSV.dev daily
  - `c28156f` feat(radar): Phase 6 — the daily radar audits SYRAX's own dependencies
  - `225e21d` fix(security): next 16.2.10 -> 16.3.8 and npm audit fix: 0 known vulnerabilities
  - `067aad7` fix: journal who stopped a task; the gate reads git output as UTF-8
  - `2be807f` feat(memory): Phase 5 — knowledge consolidates: duplicates reinforce, contradictions get settled
  - `82f1f4a` feat(brains): Phase 7 — the brain measured best at a kind of work goes first for it
  - `43f694b` feat(skills): Phase 3 — skills evolve from real use; repeated requests become skill proposals
  - `f3e7c64` fix(editor): a file's final newline no longer shows as an extra empty line
  - and 3 more

## 2026-10-01

- Tasks: 97 finished, 0 failed (3003 journal events).
- Objectives closed: 22
  - #21 Quality case `research_cite` failed in the last two runs (tool research used → tools: ['kn
  - #21 Quality case `research_cite` failed in the last two runs (tool research used → tools: ['kn
  - #23 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #24 My biggest measured limitation right now: 157 of 471 brain calls in the last 24 h failed o
  - #27 My biggest measured limitation right now: `python_execute` failed 26 of 108 uses (24%). Im
  - #22 Quality case `self_version` failed in the last two runs (final matches faa5867 → Done.). R
  - #28 My biggest measured limitation right now: Frontend HUD: history/today views are polled on 
  - #29 My biggest measured limitation right now: Frontend HUD: HUD regions (orb, controls, consol
- Incidents: interrupted 2, rollbacks 3, restarts 12.
- Commits by its maintainers: 37
  - `34dd1a2` fix(guard): code SYRAX runs cannot kill processes it did not start, power off, or change system conf
  - `8f784ec` fix(skills): refuse skill code that can hurt the host, before its tests run
  - `1e48d63` feat(quality): act, don't talk — four cases that fail a reply which promises, asks or only claims
  - `ad77e01` feat(autonomy): Phase 1 — a blocked objective's evidence decides the next objective
  - `86b4fe3` feat(autonomy): Phase 1 — plan steps are proven from the journal, a retry resumes at the next one
  - `9648e29` feat(ui): a MIND panel — briefing, objectives the human can reopen or drop, proposals, skills, brain
  - `82312c2` feat(devloop): Phase 4 — an autonomous release carries a change plan and its impact
  - `2977146` perf(prompt): the editor's schema costs 290 tokens instead of 632
  - `ec5e543` docs(status): where SYRAX stands on 2026-10-01 — autonomy loop, integrity rules, skills, remaining w
  - `8606ab0` feat(brains): Phase 7 — a scorecard of what each brain actually achieves
  - `c37742f` feat(review): a different brain must clear SYRAX's autonomous changes before commit
  - `5663211` feat(radar): Phase 6 — SYRAX watches its brains' catalogues for new models
  - `54319be` feat: daily briefing from the journal; fpdf2 for SYRAX's own PDF skill
  - `e20aeb0` feat(autonomy): Phase 5 — the brief recalls similar past objectives
  - `432f16b` fix(autonomy): a skill objective needs the skill's files, not only its registry row
  - `db12698` fix(skills): skills SYRAX builds live outside git, so rollback cannot delete them
  - `772c194` feat(skills): objectives that close only when SYRAX's own skill is verified
  - `c353ce1` feat(desktop): window control on Windows; background SYRAX opens no console windows
  - `d2127f3` docs: Phase 1 progress (self-restart, value priority, proposals); comparison with Brahma AI Evo
  - `97edad7` feat(autonomy): SYRAX restarts itself into newly committed code
  - `cea3a24` feat(limits): priority = impact x confidence / cost, measured per limitation kind
  - `0f46803` fix(brains): a provider with a key but no model picks the largest listed one
  - `0f9fdf4` feat(autonomy): researched limitations end in proposals for the human
  - `96d1215` feat(autonomy): Phase 2 — strategy fingerprints; a failed strategy is not tried again
  - `17fd8d5` feat(self): journal_query — SYRAX reads its own journal with read-only SQL
  - and 12 more

## 2026-09-30

- Tasks: 66 finished, 21 failed (2062 journal events).
- Objectives closed: 20
  - #1 Verify that the `browser_exec` tool works on this machine by calling it with a harmless, r
  - #2 Verify that the `browser_screenshot` tool works on this machine by calling it with a harml
  - #3 Verify that the `desktop` tool works on this machine by calling it with a harmless, read-o
  - #4 Verify that the `know` tool works on this machine by calling it with a harmless, read-only
  - #5 Verify that the `python_execute` tool works on this machine by calling it with a harmless,
  - #6 Verify that the `recall` tool works on this machine by calling it with a harmless, read-on
  - #7 Verify that the `research` tool works on this machine by calling it with a harmless, read-
  - #8 Verify that the `skill_list` tool works on this machine by calling it with a harmless, rea
- Incidents: interrupted 3, rollbacks 1.
- Commits by its maintainers: 21
  - `dc2a754` docs: Phase 0 evidence after the first live day on Windows
  - `7183756` fix(agent): SYRAX's own step prompt; finished work is never undone
  - `b418555` fix(journal): one live owner; a second process can no longer "recover" live work
  - `d2a0faf` fix(autonomy): the brief gives the absolute repo root and the path rules
  - `d0db000` fix(agent): a task that ran tools but said nothing gets a real final answer
  - `ac13933` feat(self): self_inspect reads one journaled task; identity says where the code is
  - `faa5867` fix(prompt): an explicit "research" means research; a final reply carries the answer
  - `f84216c` feat(brains): Upstage Solar provider; Gemini defaults to 3.5-flash-lite
  - `2f32887` fix(quality): eval and autonomous tasks start clean; free-tier brains measured, not guessed
  - `b03ed1f` fix(reliability): present accepts common synonyms; quality file_create starts clean
  - `78b8943` fix(selfmodel): version is the loaded code; restart_pending when HEAD moved
  - `b5035f0` fix(brains): clip extra system manuals so Groq fits at all
  - `a3de5c4` fix(brains): fit a huge turn by clipping, never cut a task from its request
  - `3cd2e8c` fix(server): core jobs outlive the tab that started them
  - `504ec15` fix(brains): key-less retry also drops temperature and caps max_tokens
  - `ab1cb59` docs: mission, roadmap, and a persona that grows
  - `56e7cdf` fix(brains): requests fit each brain's token budget; 413 retried once smaller
  - `debc511` fix(core): post-task rollback only touches files the task's tools could have written
  - `3e3521f` fix(brains): key-less tier answers plain chat when tools get HTTP 402
  - `5544e88` feat(launcher): one command on Windows, Linux and macOS; macOS backends
  - `fcc4c87` feat(windows): SYRAX runs natively on Windows 11
