# SYRAX devlog

Generated 2026-10-29 08:38 +0600 by `python -m syrax.devlog` at commit `a310015`, from the journal and git: one entry per day SYRAX ran, newest first. Nothing here is typed by hand; the numbers behind the trends are in [RISE.md](RISE.md).

## 2026-10-29

- Tasks: 4 finished, 0 failed (170 journal events).
- Objectives closed: 2
  - #51 My biggest measured limitation right now: Core: brain events from a running task are journ
  - #52 My biggest measured limitation right now: Journal: file edits are reality-checked and call

## 2026-10-28

- Tasks: 90 finished, 3 failed (3588 journal events).
- Objectives closed: 22
  - #27 Learn how to do what objective #17 could not: Verify that the `remind` tool works on this 
  - #28 Verify that the `remind` tool works on this machine by calling it with a harmless, read-on
  - #29 Learn how to do what objective #19 could not: Verify that the `undo` tool works on this ma
  - #30 Verify that the `undo` tool works on this machine by calling it with a harmless, read-only
  - #32 My biggest measured limitation right now: skill `flight_search` v1 failed 2 of 3 real uses
  - #33 My biggest measured limitation right now: Frontend HUD: HUD regions (orb, controls, consol
  - #34 My biggest measured limitation right now: WebSocket server + Session: an allowed Origin is
  - #35 Build the feature 'Largest files and disk usage' ('What is filling my disk?') How: a read-
- Quality run #1: 100.0 % of 10 cases.
- Incidents: rollbacks 3, claims sent back 11.
- Commits by its maintainers: 14
  - `a310015` docs: AUDIT_2026-10-28, the Linux audit and what is still open
  - `b54baf9` fix(security): git hooks and worktree links cannot run SYRAX's code
  - `9aca03c` build: declare psutil, which the code already imports
  - `5fb49de` feat(lifecycle): bounded journaled shutdown; release.live after restart
  - `c8c1427` feat(research): GitHub discovery and stale-knowledge marking
  - `c24b2fb` feat(autonomy): controller states, why-chosen records and budgets
  - `093f56e` fix(linux): the Windows-written suite passes on Linux
  - `2b164f6` fix(security): the release gate's tests run inside a write boundary
  - `0328d17` fix(brains): Ollama's budget is the server's real context
  - `797ad7f` fix(security): protected-target checks follow symlinks
  - `a3ee3c0` feat(control): a persistent emergency stop the agent cannot clear
  - `e17757d` fix(security): python_execute workers are spawned and kernel-confined
  - `8f6380d` fix(honesty): the clock is read, never invented
  - `d9621a1` fix(brains): a reply that is only a JSON tool call is a call

## 2026-10-27

- Tasks: 51 finished, 0 failed (1657 journal events).
- Objectives closed: 11
  - #11 My biggest measured limitation right now: Frontend HUD: history/today views are polled on 
  - #13 Verify that the `flight_search` tool works on this machine by calling it with a harmless, 
  - #14 Verify that the `journal_query` tool works on this machine by calling it with a harmless, 
  - #18 Verify that the `repo_map` tool works on this machine by calling it with a harmless, read-
  - #20 Verify that the `watch_topic` tool works on this machine by calling it with a harmless, re
  - #21 Verify that the `weather` tool works on this machine by calling it with a harmless, read-o
  - #22 Verify that the `youtube_transcript` tool works on this machine by calling it with a harml
  - #23 Learn how to do what objective #15 could not: Verify that the `organize_folder` tool works
- Incidents: interrupted 1, rollbacks 4, claims sent back 4.
- Commits SYRAX made to itself: 1
  - `3d7298f` syrax: docs(rise): the ledger, the devlog and the capability matrix, regenerated from evidence
- Commits by its maintainers: 80
  - `e584485` docs: quality run #88 read case by case in SYRAX_STATUS
  - `f139e5e` fix(agent): work promised for a later step is a promise
  - `a8254bd` fix(desktop): find_files reads *, ? and [ as a wildcard pattern
  - `6efa7ee` feat(rise): objectives done that needed a landed change; the human share of commits
  - `0f71b3c` docs: the audit's open items closed in SYRAX_STATUS; knowngood in the system map
  - `809ed8b` feat(launcher): known-good fallback when a restarted core does not come up
  - `a83ffa0` fix(autonomy): settle objectives follow DISPUTED rows; only ACTIVE knowledge is evidence
  - `f105cbb` fix(rise, phases, core): read the claim rules from syrax.claims, not through agent.py
  - `b2da2af` refactor(claims): the claim-check rules move to claims.py, a judge
  - `7c06fde` fix(knowledge): rows keep their own ACTIVE / DISPUTED / SUPERSEDED state
  - `7011b95` fix(permissions): a desktop Enter in a messaging app is a send
  - `727108c` docs: skills run in a guarded process of their own (SKILLS, SYSTEM_MAP)
  - `fa44e0b` fix(skills): a skill call runs in a guarded process of its own, killed on timeout
  - `3ce2804` feat(agent): clipboard, screen, window, media and MCP text is marked untrusted
  - `4534909` fix(hud): the solar wind and Kp feeds read NOAA's current products
  - `2c2fe63` test: integration fixes for the sweep's new tests
  - `b0a700f` docs: the 2026-10-27 bug sweep in SYRAX_STATUS
  - `77b7989` fix(core): requests queued in one clock tick keep the order they came in
  - `4aa98be` fix(server): a HUD feed that fails is quiet: one log line an hour, no upstream call per poll
  - `7057b4f` fix(core): a queued request that cannot start no longer stalls the queue
  - `66280e6` fix(core): a cancel during a task's cleanup no longer leaves the core stuck
  - `98b0732` fix(core): a restart's stop holds the queue instead of starting the next request
  - `b1b9958` fix(core): after a resume the next message continues the resumed conversation
  - `5532939` fix(core): a resume waits for a starting task instead of launching beside it
  - `2ec70ea` fix(agent): words after a given diff are not read as its lines
  - and 55 more

## 2026-10-02

- Tasks: 0 finished, 0 failed (6 journal events).

## 2026-10-01

- Tasks: 6 finished, 0 failed (94 journal events).
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

- Tasks: 12 finished, 0 failed (184 journal events).
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

## 2026-09-27

- Tasks: 13 finished, 0 failed (170 journal events).
- Objectives closed: 9
  - #1 Verify that the `browser_exec` tool works on this machine by calling it with a harmless, r
  - #2 Verify that the `browser_screenshot` tool works on this machine by calling it with a harml
  - #3 Verify that the `desktop` tool works on this machine by calling it with a harmless, read-o
  - #4 Verify that the `know` tool works on this machine by calling it with a harmless, read-only
  - #5 Verify that the `python_execute` tool works on this machine by calling it with a harmless,
  - #6 Verify that the `recall` tool works on this machine by calling it with a harmless, read-on
  - #7 Verify that the `research` tool works on this machine by calling it with a harmless, read-
  - #8 Verify that the `self_inspect` tool works on this machine by calling it with a harmless, r
