# SYRAX devlog

Generated 2026-10-31 19:48 +0600 by `python -m syrax.devlog` at commit `f9249dd`, from the journal and git: one entry per day SYRAX ran, newest first. Nothing here is typed by hand; the numbers behind the trends are in [RISE.md](RISE.md).

## 2026-10-31

- Tasks: 6 finished, 1 failed (520 journal events).
- Incidents: interrupted 1, rollbacks 1, claims sent back 4.
- Commits SYRAX made to itself: 1
  - `5ae75ed` syrax: docs(rise): the ledger, the devlog and the capability matrix, regenerated from evidence
- Commits by its maintainers: 23
  - `f9249dd` docs(progress): Now, Open and Next rewritten for the end of 2026-10-31
  - `8f1d560` docs(progress): publish proven live; next 16.4.2 security fix
  - `40f7988` fix(security): next 16.3.8 -> 16.4.2 (critical: unauthenticated RCE in image optimization, DoS in se
  - `808cf39` docs(progress): the daily ledger publish fixed on Linux (git config names were scrubbed as secrets)
  - `6003faf` fix(gate): git works inside the confined gate again, and the matrix report is written where it may b
  - `f732b2c` docs(progress): quality 63/67 after the day's changes; three misses pass on rerun or are a known bra
  - `e885d65` fix(repo_map): judges in devloop's order, the main ones first
  - `8a0360c` fix(repo_map): the protected line names the judges by file name
  - `e085864` docs: plan status after deciding the last MISSING items (149 / 110 / 3 waiting for the owner); progr
  - `122d1f6` feat(memory): a request that goes against an owner's rule is named to the brain, which says so and a
  - `f9e979c` feat(rise): the human's requests that cost them nothing more (plan direction 298); design note for t
  - `5b3565f` docs(progress): Ollama answers on this PC with the short persona, verified live
  - `974ad37` feat(brains): a brain too small for the full persona gets a short one, so Ollama can answer
  - `d81149c` docs(progress): Groq answers again with per-request tools, verified live
  - `b711941` feat(brains): a small brain gets the tools a request needs when even the compact manual does not fit
  - `1816eaa` docs(progress): language follows the current message, verified live
  - `8677d5a` fix(language): the current message decides the answer's language
  - `d90f62c` docs(progress): undo, scenes and the phone page from the Ultron comparison
  - `e1dc4c4` feat(phone): watch SYRAX and press the emergency stop from a phone on the home WiFi
  - `ba55178` feat(scenes): 'coding mode', 'research mode', 'chill mode' set the computer up in one request
  - `31243a0` feat(undo): volume, GNOME dark mode and trashed files can be undone
  - `1e5e070` docs(progress): first night with the new code, tuning live, host-acting skills fixed; real times
  - `664d1ad` fix(permissions): code that acts on the host's screen or input is SYSTEM, whatever a skill declares

## 2026-10-30

- Tasks: 23 finished, 1 failed (993 journal events).
- Objectives closed: 6
  - #55 My biggest measured limitation right now: Journal: maintenance never deletes tasks, knowle
  - #56 Verify that the `data_query` tool works on this machine by calling it with a harmless, rea
  - #57 Verify that the `logic_check` tool works on this machine by calling it with a harmless, re
  - #58 Verify that the `paper_search` tool works on this machine by calling it with a harmless, r
  - #59 My biggest measured limitation right now: Self-model: GPU load and memory in use are known
  - #60 My biggest measured limitation right now: Self-model: system_map.json is hand-audited and 
- Quality run #3: 81.8 % of 11 cases; failed: deep2_data_pipeline, deep2_log_report.
- Incidents: rollbacks 1.
- Commits by its maintainers: 57
  - `8417c9e` docs: plan direction 87 exists (prior tuning); progress
  - `9a2d896` feat(calibrate): the success prior's strength is tuned from history, prequentially
  - `5387cf6` docs: plan direction 100 exists (skill generalization proposals); progress
  - `3be477a` feat(skills): the daily radar proposes one general skill for two that serve one subject
  - `86d3423` docs: plan direction 18 exists (expected-value ranking); progress
  - `a759514` feat(autonomy): same-priority objectives go by expected value (success / cost), not age alone
  - `c54a4f9` docs(progress): full live test, quality 66/67 (the miss passes on rerun), new tools and one autonomy
  - `6b2e004` docs: disk trend, lesson transfer, research value-of-information; plan status
  - `a2a4f11` feat(research): stored, fresh knowledge answers before a web search is made
  - `ee435b9` feat(autonomy): a lesson learned on one subject reaches another with the same check
  - `3a82fc2` feat(alerts): the disk's trend, not only its level
  - `1489f95` docs: new capabilities (data_query, logic_check, paper_search, heat, contradictions); plan status
  - `27b6dc9` feat(tools): logic_check decides whether premises entail a conclusion
  - `08667d8` feat(consolidate): a different answer to a single-answer relation is a contradiction
  - `91dd65f` feat(research): paper_search finds arXiv papers and keeps them as sourced knowledge
  - `2566684` feat(alerts): SYRAX warns when the hardware runs hot
  - `d6fe362` feat(tools): data_query reads a CSV/TSV or SQLite file with read-only SQL
  - `9f56d34` docs(progress): the GNOME focus extension, and the owner's step to turn it on
  - `7ae34be` feat(desktop): the window in front on GNOME, through SYRAX's own shell extension
  - `012742e` docs(progress): Linux screenshots work through the portal
  - `9d6a41d` feat(desktop): screenshots on GNOME Wayland through the Screenshot portal
  - `756e699` docs(progress): the three owner decisions, Linux input, and the ctrl+c incident
  - `d156a11` test: tests never reach the real keyboard, mouse or theme
  - `3b8dfa0` feat(desktop): keyboard, mouse and dark mode on Linux GNOME (Wayland), no root
  - `1862185` feat(persona): a request in Bengali script is answered in Bengali
  - and 32 more

## 2026-10-29

- Tasks: 18 finished, 0 failed (852 journal events).
- Objectives closed: 4
  - #51 My biggest measured limitation right now: Core: brain events from a running task are journ
  - #52 My biggest measured limitation right now: Journal: file edits are reality-checked and call
  - #53 My biggest measured limitation right now: skill `disk_usage` v4 failed 1 of 3 real uses si
  - #54 My biggest measured limitation right now: Journal: PENDING tasks are stored but not schedu
- Quality run #2: 90.0 % of 10 cases; failed: deep_spec_tests.
- Incidents: claims sent back 3, restarts 3.
- Commits SYRAX made to itself: 1
  - `46d4abb` syrax: docs(rise): the ledger and the devlog, regenerated from the journal
- Commits by its maintainers: 40
  - `89999c8` Merge branch 'main' of github.com:saimunprince/son-of-ultron
  - `75bb8a8` Merge branch 'main' of github.com:saimunprince/son-of-ultron
  - `766e4b0` docs(progress): skill-remove and no-answer fixes live, flight_search re-enabled
  - `bee0cd0` fix(agent): an admitted non-answer ends PARTIAL, not SUCCESS
  - `5187f91` fix(permissions): own work never removes a skill
  - `57e96cc` docs(progress): the audit mission's first fixes, what is in the gate, the open list
  - `0c9f898` fix(ui): controls say when the link is down; no double queue; HUD stops inventing
  - `0b1feb9` fix(estop): a stop pressed while own work starts keeps it from running
  - `0723a96` fix(skills): a skill for another OS is never offered as a tool here
  - `4b71544` fix(autonomy): the daily budget counts this PC's own tasks, in the journal
  - `1beaab3` docs: PROGRESS.md, the current stage at a glance
  - `56f9b80` test: Linux-only checks skip on Windows; hidden .git rewritten in place
  - `d114c56` fix(gitignore): the journal chain key is a secret too
  - `2d86456` docs(audit): close the owner's three calls and the 10-29 fixes
  - `87426c9` perf(confine): build the human boundary with string prefixes
  - `3f51107` feat(confine): a human's python_execute gets a kernel boundary of its own
  - `1ac0b80` feat(devloop): agent.py and brains.py join the judges
  - `054153f` fix(backup): the journal's chain key travels with the journal
  - `f3211e2` fix(agent): import STAGED with the other claims rules
  - `70e7437` fix(claims): a failure printed as fixed text is staged, not observed
  - `421c75b` fix(estop): name the running task before stopping the loop
  - `8a2b5d2` fix(confine): cap writable memory (RLIMIT_DATA), not address space
  - `1a118ed` fix(autonomy): own work's brief states its kernel boundary and level
  - `735b2b3` feat(control): autonomy.toggled records who turned it on or off
  - `ae7f926` fix(linux): python and pytest by name; skills may read config.toml
  - and 15 more

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

- Tasks: 12 finished, 0 failed (89 journal events).
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
