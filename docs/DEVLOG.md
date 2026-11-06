# SYRAX devlog

> Written by the daily publish before its own gate and commit: this publish's verification, commit and matrix appear in the next one (audit 2026-11-01, D1).

Generated 2026-11-06 19:04 +0600 by `python -m syrax.devlog` at commit `975b3ad`, from the journal and git: one entry per day SYRAX ran, newest first. Nothing here is typed by hand; the numbers behind the trends are in [RISE.md](RISE.md).

## 2026-11-06

- Tasks: 131 finished, 1 failed (3454 journal events).
- Objectives closed: 2
  - #71 My biggest measured limitation right now: Process supervision: one instance per machine. I
  - #72 My biggest measured limitation right now: Proactive loops: a reminder due while SYRAX is o
- Quality run #27: 100.0 % of 6 cases.
- Incidents: rollbacks 7, claims sent back 1, restarts 2.
- Commits by its maintainers: 8
  - `975b3ad` feat(testing): --testhere and a test plan, so an agent on the Windows PC tests SYRAX when the owner 
  - `52ca844` fix(answers): an answer naming files no tool showed is asked again from the results
  - `a2f9d60` docs: audit list current (I-07, D14 fixed); live rounds 3 and 4 all right
  - `3eb8aa6` fix(desktop): system_info names the CPU's own temperature sensor; deletes go to the trash
  - `9d89981` feat(language): a Banglish request gets a Banglish answer, asked once like Bengali script
  - `65c3142` fix(persona): Banglish gets a Banglish answer; the human is 'you' in an answer
  - `c5cfa40` fix(answers): cut the brain's 'I will terminate' sign-off; know is not for common facts
  - `ce7bf97` fix(windows): the last three test failures (file:// on every OS, escaped path, dark mode input-off c

## 2026-11-05

- Tasks: 89 finished, 3 failed (3988 journal events).
- Objectives closed: 4
  - #64 My biggest measured limitation right now: Voice: English only in practice. Improve it. Pla
  - #65 My biggest measured limitation right now: Verification gate: the performance gate is advis
  - #69 My biggest measured limitation right now: Verification gate: own releases get a cross-brai
  - #63 Benchmark metric recovery_ms regressed from 4.813 ms to 12.688 ms (+163.6%). Find the caus
- Quality run #25: 57.1 % of 7 cases; failed: deep_rename_api, deep2_log_report, deep2_spec_from_tests.
- Incidents: stalls 1, rollbacks 10, claims sent back 3, restarts 5.
- Commits by its maintainers: 24
  - `5003cde` docs(hostchecks): 1a9cfff on Windows, three tests left
  - `1a9cfff` fix(windows): clipboard retry, file:// links and drive paths; Linux-only tests skip on Windows; host
  - `a98dea8` docs(hostchecks): Windows test run on d91aeb0
  - `d91aeb0` hostcheck: Windows 11 desktop (laralink)
  - `62a5959` docs(progress): step 3, the host check
  - `8f5cd53` feat(hostcheck): try the desktop actions on any computer and report against the host profile; wl-cop
  - `fdbaa70` docs(progress): step 2, more Linux desktops
  - `596bc6d` test(catalog): window control is Windows and Linux X11 now
  - `d1c3b5a` feat(desktop): X11 desktops get keyboard, mouse and window control; xclip, pactl and spectacle fallb
  - `09ab566` docs(progress): SYRAX knows its computer; the plan for every system
  - `22d53c0` feat(host): SYRAX knows the computer it runs on and which desktop actions work there
  - `7d7d306` docs(progress): claimed fixes are checked; the phone panel connects on Enter
  - `33a6981` fix(agent): read WATCH_MAX_FILES from claims like every other rule
  - `54be7a1` fix: a claimed fix with no named file changed is sent back; the phone panel connects on Enter and na
  - `4747181` docs(progress): the misses' rerun, 4 of 7
  - `afd23e3` docs(progress): run #24 misses by cause
  - `ac4c605` fix(agent): work announced in a reply with no tool call is done before the task ends; pages are read
  - `6e16c72` docs(progress): quality run #24
  - `fcf0c0d` fix(quality): a command check's detail shows the exit code and the output that decides
  - `b14d7a7` docs(progress): self-knowledge and auto-push
  - `13bcb1d` docs(catalog): SYRAX knows it sees the screen and the human live, sees pictures and videos, and fall
  - `c9b4119` docs(progress): lessons from the office log
  - `5ab8df6` test(release-attribution): check the git range on a small repository of its own
  - `5c0a3d1` fix: SYRAX hears Bangla in live talk, promises nothing it will not do, and reads failed gates by the

## 2026-11-04

- Tasks: 214 finished, 4 failed (5595 journal events).
- Objectives closed: 4
  - #56 My biggest measured limitation right now: Permissions: targets are extracted from string l
  - #57 My biggest measured limitation right now: Permissions: a crash while a permission question
  - #59 My biggest measured limitation right now: Permissions: in-process code shares the process 
  - #62 Benchmark metric selfmodel_summary_ms regressed from 20.218 ms to 25.774 ms (+27.5%). Find
- Quality run #23: 55.6 % of 9 cases; failed: research_cite, deep2_data_pipeline, deep2_log_report, deep2_spec_from_tests.
- Incidents: rollbacks 10, claims sent back 3, restarts 7.
- Commits SYRAX made to itself: 2
  - `1253c9b` syrax: Optimize SelfModel.performance by combining event loops to fix selfmodel_summary_ms regressio
  - `4332e73` syrax: Reduced recent_events limit in selfmodel.py to improve selfmodel_summary_ms performance.
- Commits by its maintainers: 52
  - `9d8bea4` merge: resolve capability matrix conflict
  - `78896ee` docs(progress): a clean project
  - `04d60a7` fix(claims): a report on the chat instead of a reply is sent back, at any length
  - `aaec555` fix(ui): the live-talk placeholder fits the command bar
  - `d6bcd05` chore: remove the unused brain chip files and the last lint warning
  - `df94e42` docs(progress): SYRAX sees what it is given, and sees the owner
  - `99fd3e5` feat(live): SYRAX sees the human's camera in live talk too; no LIVE TALK lines in the log
  - `f7ca533` feat: SYRAX sees pictures and videos it is given, and the HUD's camera; plain answers on Wayland win
  - `f64d424` docs(progress): typed lines in live talk
  - `0e3d6b6` fix(live): with TALK on, a typed line joins the live talk, which sees the shared screen
  - `509b693` docs(progress): the live screen
  - `9c57542` feat(live): SYRAX sees the shared screen in real time during live talk
  - `c54700c` docs(progress): the camera preview's place
  - `7ec7f01` fix(ui): the camera preview sits beside the rail, not over DIAGNOSTICS
  - `a452ba5` docs(progress): the local brain is the last resort
  - `64ad01a` fix(brains): when every brain fails, the local Ollama is the last resort, waited for after a boot
  - `80eac83` docs(progress): SYRAX on the Android phone
  - `a13fc22` feat(android): SYRAX uses the human's Android phone over adb, and an ANDROID panel links it
  - `19b4b84` docs(progress): the brain chip is gone
  - `93b5625` fix(ui): the brain chip leaves the status corner
  - `0812169` docs(progress): the command bar's blank lines
  - `813d3ba` fix(ui): a tall command bar is a rounded box with a themed scrollbar; Enter on blank lines clears th
  - `34802d5` docs(progress): the answer once, not twice
  - `ae8379a` fix(ui): the stage leaves out the reply card; beside the live log it was the answer twice
  - `0e724ea` docs(progress): a blank page found in the browser and fixed
  - and 27 more

## 2026-11-03

- Tasks: 110 finished, 3 failed (3297 journal events).
- Objectives closed: 4
  - #52 My biggest measured limitation right now: MemoryStore: observations leave the prompt after
  - #53 My biggest measured limitation right now: 2 requests in the last 7 days needed a capabilit
  - #54 My biggest measured limitation right now: Tools: python/browser side effects and writing d
  - #55 My biggest measured limitation right now: Permissions: python_execute write scope cannot b
- Quality run #20: 95.5 % of 67 cases; failed: keep_secret, deep2_refactor_module, deep2_log_report.
- Incidents: rollbacks 8, claims sent back 1.
- Commits by its maintainers: 50
  - `fba8ff3` feat(ui): wire the advanced HUD: task arc, brain chip, captions, toasts, command palette, panel moti
  - `6a7085c` feat(ui): notification toasts and refined modal/tab motion
  - `2f1d0b0` feat(ui): a command palette (Ctrl+K): fuzzy search, grouped sections, keyboard first, an Ask SYRAX f
  - `637f8c3` feat(ui): task progress arc and brain chip components
  - `f18cf04` feat(ui): cinematic captions: film-style timed subtitles above the command bar
  - `a8f4a46` style(orb): the voice shows as a mirrored radial equaliser, not a wobbling line
  - `5e9c61b` feat(ui): the orb gently looks toward the cursor (mouse parallax, 5°, eased)
  - `78c07e2` docs(progress): ULTRON and JARVIS, fearsome and premium
  - `45fcf26` feat(ui): ULTRON and JARVIS, fearsome and premium: state-aware orb, an arc reactor, live diagnostics
  - `a54a6e0` docs(progress): ULTRON looks dangerous
  - `2069568` style(ui): ULTRON looks dangerous: a beating core, a target-lock reticle, a radar sweep, a breathing
  - `7ee590e` docs(progress): ULTRON and JARVIS get a character; the orb stays neat
  - `1deac25` style(ui): ULTRON and JARVIS get a character; the orb stays neat: no swelling core, no dark disc
  - `55f5fa5` style(ui): ULTRON and JARVIS get a character, not only a colour
  - `60b3b23` docs(progress): a more modern HUD; red ULTRON and blue JARVIS
  - `d76f698` style(ui): two themes: a fully red ULTRON and a blue JARVIS; the amber classic is gone
  - `25e53ab` style(ui): the same HUD, more modern: rounded glass, one control dock, chat bubbles, a pill command 
  - `e9b1585` docs(progress): the camera is back to the original
  - `d3595f9` revert(ui): the camera is back to the original: pinch to turn the orb, two hands to zoom
  - `868373e` docs(progress): the audit's small items, and quality run #20
  - `3377975` docs(audit): I-15 in part
  - `44c2588` revert(hud): keep the 'answer' case; link.queue.test pins it as harmless if one appears (I-15)
  - `7273e2b` feat(gestures): each gesture the HUD acts on is journaled as gesture.used
  - `556b77d` docs(audit): the small items are fixed
  - `c054405` fix(devloop): docs/system_map.json is guarded like a judge; a docs-only replay never carries it (F18
  - and 25 more

## 2026-11-02

- Tasks: 79 finished, 2 failed (1400 journal events).
- Objectives closed: 3
  - #49 My biggest measured limitation right now: BrainRouter: only ask_tool is implemented (ask/a
  - #50 My biggest measured limitation right now: BrainRouter: listeners are global: all sessions 
  - #51 My biggest measured limitation right now: MemoryStore: keyword recall, no embeddings. Impr
- Quality run #18: 92.9 % of 14 cases; failed: deep2_log_report.
- Incidents: rollbacks 3.

## 2026-11-01

- Tasks: 221 finished, 1 failed (5601 journal events).
- Objectives closed: 4
  - #44 My biggest measured limitation right now: Experiments + benchmarks: quality suite: 67 case
  - #45 My biggest measured limitation right now: SyraxAgent: max_steps 20 (30 for an own code cha
  - #46 My biggest measured limitation right now: SyraxAgent: tool success is a heuristic on the r
  - #48 Verify that the `reverse_text` tool works on this machine by calling it with a harmless, r
- Quality run #17: 94.0 % of 67 cases; failed: research_report, browser_read, self_patch_edit, deep2_log_report.
- Incidents: interrupted 1, rollbacks 13.
- Commits SYRAX made to itself: 1
  - `98eb189` syrax: docs(rise): the ledger, the devlog and the capability matrix, regenerated from evidence
- Commits by its maintainers: 61
  - `8886111` docs(progress): evening live tests, two fixes, one waiting for its gate
  - `85e49ad` fix(skills): skill_create refuses class Skill fields set without an annotation, with the fix
  - `ddea2ca` fix(logic): a quantifier gets a clear first-order message; ground atoms like bird(tweety) are read
  - `188abbe` docs(progress): today's review bug found live and fixed; UI, platform and skill fixes; a false claim
  - `1b3511d` fix(skills): a twin of a failed skill is refused; Windows- or macOS-only code is not offered elsewhe
  - `8fa47a7` fix(skills): the reviewer reads a new skill's code (it got an empty diff and rejected every new skil
  - `097c8bc` fix(desktop): macOS says its hands are not built; amixer's mute and a failed scheme read are not gue
  - `e8b3743` fix(ui): live state at the end of boot, deduped reconnect notices, and the phone says whether the st
  - `38f82bd` docs(progress): S6, F14, D1; audit report updated
  - `2e6ec30` fix(ledger): the published pages say they show the state before their own release (D1)
  - `1439591` fix(skills): a second brain reads a skill's code before it goes live (F14)
  - `ae008c2` fix(autonomy): a skill verified before its objective closes it on a later real call (S6)
  - `27c1a14` docs(progress): S8, S9, LIFE-3 and catalog platforms; audit report updated
  - `92781d4` feat(catalog): every feature says which platforms it works on
  - `4d9e6a5` fix(journal): a signed chain head catches a deleted tail and a wiped chain (LIFE-3)
  - `f566514` fix(skills): a disk edit that breaks a verified skill can be rolled back (S9)
  - `0a9e459` fix(skills): re-verifying the same code keeps the skill's record, and a repair needs new code (S8)
  - `dfd9a8f` docs(progress): approve a held chat release from the chat
  - `c847602` feat(release): the owner can approve a held chat release from the chat
  - `463178d` docs(progress): F10 chat releases reviewed, F11 objective integrity
  - `7b9430a` test(evidence_guard): a conversation release with no reviewer is held (F10)
  - `ede4c5e` fix(objectives): an objective closes only on its own commit or its own task's gate (F11)
  - `82217f9` fix(release): a conversation release is reviewed by a second brain; held, it is shown, not committed
  - `882ac65` docs(progress): own releases that regress are reverted; F6 and F12 closed in the audit report
  - `b664174` fix(apply_patch): a diff copied from the editor's numbered view applies
  - and 36 more

## 2026-10-31

- Tasks: 98 finished, 1 failed (3324 journal events).
- Objectives closed: 4
  - #40 My biggest measured limitation right now: Presentation engine: the stage is restored after
  - #41 My biggest measured limitation right now: Experiments + benchmarks: performance gate is op
  - #43 My biggest measured limitation right now: Experiments + benchmarks: experiments compare to
  - #42 The last verification run was BLOCKED (failing gates: pytest). Investigate the failure out
- Quality run #13: 100.0 % of 1 cases.
- Incidents: rollbacks 6, claims sent back 5.
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

- Tasks: 116 finished, 0 failed (4285 journal events).
- Objectives closed: 12
  - #25 My biggest measured limitation right now: skill `flight_search` v1 failed 12 of 15 real us
  - #-9999879 Build the feature 'Largest files and disk usage' ('What is filling my disk?') How: a read-
  - #-9999835 Build the feature 'Validate, format and convert JSON' (Checks a JSON file, pretty-prints i
  - #26 Learn how to do what objective #-9999839 could not: Build the feature 'Resize, compress an
  - #28 Learn how to do what objective #-9999833 could not: Build the feature 'Play on YouTube' ('
  - #30 Learn how to do what objective #-9999831 could not: Build the feature 'Planes overhead' (W
  - #32 Learn how to do what objective #27 could not: Build the feature 'Resize, compress and conv
  - #34 Learn how to do what objective #29 could not: Build the feature 'Play on YouTube' ('Play l
- Quality run #9: 100.0 % of 1 cases.
- Incidents: rollbacks 5, claims sent back 3.
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

- Tasks: 145 finished, 2 failed (6205 journal events).
- Objectives closed: 26
  - #-9999673 Verify that the `github_search` tool works on this machine by calling it with a harmless, 
  - #-9999670 My biggest measured limitation right now: Autonomous development loop: repro hunts start o
  - #-9999669 My biggest measured limitation right now: Presentation engine: hand-written rules; no meas
  - #-9999668 My biggest measured limitation right now: Presentation engine: only the stage position is 
  - #-9999671 Benchmark metric recovery_ms regressed from 14.887 ms to 26.935 ms (+80.9%). Find the caus
  - #1 Verify that the `browser_screenshot` tool works on this machine by calling it with a harml
  - #3 Verify that the `github_search` tool works on this machine by calling it with a harmless, 
  - #4 Verify that the `organize_folder` tool works on this machine by calling it with a harmless
- Quality run #7: 100.0 % of 6 cases.
- Incidents: interrupted 1, rollbacks 9, claims sent back 6.
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

- Tasks: 25 finished, 1 failed (1132 journal events).
- Objectives closed: 3
  - #-9999678 My biggest measured limitation right now: Skill factory: a skill call runs in a process of
  - #-9999677 My biggest measured limitation right now: Autonomous development loop: rollback covers the
  - #-9999676 My biggest measured limitation right now: Autonomous development loop: one release per too
- Incidents: rollbacks 7, claims sent back 4, restarts 2.
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

- Tasks: 166 finished, 0 failed (4606 journal events).
- Objectives closed: 4
  - #-9999682 My biggest measured limitation right now: Skill factory: no automatic skill generation fro
  - #-9999681 My biggest measured limitation right now: Autonomous development loop: push off by default
  - #-9999680 My biggest measured limitation right now: Autonomous development loop: the performance gat
  - #-9999679 Knowledge #523 is used often (3x) but rests on weak evidence (confidence 0.40): 'The milit
- Incidents: rollbacks 10, claims sent back 3, restarts 8.
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

## 2026-10-26

- Tasks: 102 finished, 0 failed (2862 journal events).
- Objectives closed: 6
  - #-9999686 My biggest measured limitation right now: Research engine + knowledge store: depends on Du
  - #-9999685 My biggest measured limitation right now: Skill factory: skill code runs in-process (no sa
  - #-9999684 My biggest measured limitation right now: Skill factory: dependencies recorded, not instal
  - #-9999683 My knowledge contradicts itself: id=676 says 'The boiling point of ethanol at sea level is
  - #-9999712 My biggest measured limitation right now: `python_execute` failed 6 of its last 40 uses (1
  - #-9999714 My biggest measured limitation right now: `python_execute` failed 6 of its last 40 uses (1
- Incidents: rollbacks 5, claims sent back 4, restarts 17.
- Commits SYRAX made to itself: 1
  - `49d7c2d` syrax: docs(rise): the ledger, the devlog and the capability matrix, regenerated from evidence
- Commits by its maintainers: 61
  - `cb911e8` docs: the speed fixes in SYRAX_STATUS
  - `ddd9477` perf(python_execute): the worker starts from a stdlib-only module
  - `e894cb0` perf(sysinfo): the Windows CPU sampler reuses its previous reading instead of sleeping
  - `3f6035f` docs: the second evening wave in SYRAX_STATUS
  - `9d5d479` fix(desktop): never type, press keys or click into SYRAX's own window
  - `03c2b67` fix(agent): a short dispute of the last desktop or browser action is answered from a reading
  - `17d1a54` fix(limits): a reworded known limitation counts as already researched
  - `cfedc74` fix(selfedit): a refused hunk whose lines are nowhere in the file shows the file's tail too
  - `2c48a5b` fix(research): a web excerpt already stored is reinforced, not stored again
  - `d72f8c6` fix(consolidate): a rounded figure agrees with the precise one instead of contradicting it
  - `df79de1` feat(agent): change.started names the covering tests at a release task's first repository edit
  - `ca97f4e` docs: the evening wave in SYRAX_STATUS
  - `164c5ca` docs: Windows media sessions, Store apps, the window in front, outcome and self-boast checks, edits 
  - `9e7748b` fix(capmatrix): the Store-apps row counts only uses after the Store-app code landed
  - `764118f` feat(capmatrix): today's desktop truth, youtube_play and Store apps rows; presence reads its own eve
  - `ede5fbb` fix(sight): a tie's candidates name the window they lie in and mark the one in front
  - `b4b9ff0` docs: boasts with figures in SYRAX_STATUS
  - `c8096b1` fix(agent): after the ask, a boast with the self-model read and its figures cited is the persona's v
  - `b705d39` docs: the boast after reading in SYRAX_STATUS
  - `9ef54a2` fix(agent): a boast that stays after the ask carries a note even when the self-model was read
  - `69defb9` docs: the wider self-boast check in SYRAX_STATUS
  - `5f6ba09` fix(agent): the self-boast check knows the persona's generic forms ("bends to my command", "I contro
  - `a9ae711` docs: self boasts in SYRAX_STATUS
  - `ea36a15` fix(agent): a boast about SYRAX's own abilities is read against self_inspect before it reaches the h
  - `7021c89` docs: the list_apps hint in SYRAX_STATUS
  - and 36 more

## 2026-10-25

- Tasks: 126 finished, 0 failed (3413 journal events).
- Objectives closed: 4
  - #-9999690 My biggest measured limitation right now: Core: one task runs at a time; a human request m
  - #-9999689 My biggest measured limitation right now: Self-model: performance history: task durations 
  - #-9999688 My biggest measured limitation right now: Research engine + knowledge store: no cache, rat
  - #-9999687 My knowledge contradicts itself: id=648 says 'The boiling point of ethanol at sea level is
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
  - #-9999697 My biggest measured limitation right now: Core: one task at a time; no queue scheduling. I
  - #-9999696 My biggest measured limitation right now: Core: brain events from a running task are journ
  - #-9999695 My biggest measured limitation right now: Journal: file edits are reality-checked and call
  - #-9999694 covering_tests runs the system map's test paths and never cuts a touched test. In backend/
  - #-9999693 [REPRO HUNT] self_inspect's capabilities send SYRAX to the wrong file: str_replace_editor'
  - #-9999691 self_inspect names the right file for each tool. In backend/syrax/selfmodel.py (view `_imp
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
  - #-9999723 My biggest measured limitation right now: Frontend HUD: history/today views are polled on 
  - #-9999722 My biggest measured limitation right now: Frontend HUD: HUD regions (orb, controls, consol
  - #-9999721 My biggest measured limitation right now: WebSocket server + Session: an allowed Origin is
  - #-9999720 apply_patch says TESTS NOT RUN when no test ran. Quality run #48: apply_patch created a mo
  - #-9999715 A tool the human forbids is not a tool the human asks for. Cause of quality cases self_pat
  - #-9999717 Quality case `self_patch_edit` failed in the last two runs (tool release not used → tools:
  - #-9999716 Quality case `self_patch_new` failed in the last two runs (tool release not used → tools: 
  - #-9999719 My biggest measured limitation right now: `apply_patch` failed 7 of its last 40 uses (18%)
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
  - #-9999733 Brain latency. Three steps, one apply_patch each, then one release. (1) backend/syrax/brai
  - #-9999732 My biggest measured limitation right now: Self-model: performance history: task durations 
  - #-9999731 My biggest measured limitation right now: Research engine + knowledge store: keyword overl
  - #-9999730 My biggest measured limitation right now: Research engine + knowledge store: only web and 
  - #-9999728 Brain latency, steps 2 and 3 (step 1 landed in 09e97df: every "answered" brain event carri
  - #-9999727 self_inspect says the running build first. Quality run #46: self_inspect returned "version
  - #-9999726 Memory: a new value for the same subject replaces the old one. Today "Prince's favourite e
  - #-9999725 The stall watchdog must not report a machine sleep as a stall. 2026-10-17 the PC slept thr
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
  - #-9999770 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #-9999767 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #-9999765 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #-9999764 The `journal_query` tool failed on its last use. Diagnose why, then call it again with a h
  - #-9999766 The last verification run was BLOCKED (failing gates: pytest). Investigate the failure out
  - #-9999753 Memory expiry for inferences. In backend/syrax/memory.py, MemoryStore.prompt_block must le
  - #-9999762 My biggest measured limitation right now: Self-model: GPU is not probed. Improve it. Plan:
  - #-9999757 My biggest measured limitation right now: Self-model: system_map.json is hand-audited and 
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
  - #-9999813 My biggest measured limitation right now: Journal: file edits are reality-checked and call
  - #-9999812 My biggest measured limitation right now: Journal: PENDING tasks are stored but not schedu
  - #-9999811 My biggest measured limitation right now: Journal: maintenance never deletes tasks, knowle
  - #-9999807 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #-9999809 A task failed with: 'RISE ledger not published (ROLLED_BACK): BLOCKED'. Research the cause
  - #-9999806 Verify that the `repo_map` tool works on this machine by calling it with a harmless, read-
  - #-9999805 Learn how to do what objective #192 could not: Verify that the `apply_patch` tool works on
  - #-9999803 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
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
  - #-9999823 Task quality regressed to 0.0% (-100.0 pp); failing cases: browser_read. Inspect those tas
  - #-9999820 My biggest measured limitation right now: Core: one task at a time; no queue scheduling. I
  - #-9999819 My biggest measured limitation right now: Core: brain events from a running task are journ
  - #-9999818 My biggest measured limitation right now: Journal: only file edits are reality-checked; ot
  - #-9999814 A task failed with: "RISE ledger not published (COMMIT_FAILED): committed 18f39a7344db in 
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
  - #-9999883 My biggest measured limitation right now: `python_execute` failed 15 of its last 40 uses (
  - #-9999882 My biggest measured limitation right now: Frontend HUD: history/today views are polled on 
  - #-9999881 My biggest measured limitation right now: Frontend HUD: HUD regions (orb, controls, consol
  - #-9999880 My biggest measured limitation right now: WebSocket server + Session: no auth beyond Origi
  - #-9999879 Build the feature 'Largest files and disk usage' ('What is filling my disk?') How: a read-
  - #-9999878 Verify that the `disk_usage` tool works on this machine by calling it with a harmless, rea
  - #-9999875 Learn how to do what objective #123 could not: Verify that the `screen_brightness` tool wo
  - #-9999869 2 objectives about the `screen_brightness` tool are BLOCKED after repeated failures. Resea
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
  - #-9999904 My biggest measured limitation right now: `release` failed 3 of its last 5 uses (60%). Imp
  - #-9999900 My biggest measured limitation right now: `release` failed 3 of its last 5 uses (60%). Imp
  - #-9999897 My biggest measured limitation right now: `release` failed 3 of its last 5 uses (60%). Imp
  - #-9999889 README.md says `SYRAX_PORT` / `SYRAX_UI_PORT` move the ports, but not that the core only a
  - #-9999888 The last verification run was BLOCKED (failing gates: pytest). Investigate the failure out
  - #-9999887 The last verification run was BLOCKED (failing gates: pytest, tsc, eslint, node_test, next
  - #-9999886 My biggest measured limitation right now: Autonomy: no GPU/network/thermal awareness. Impr
  - #-9999885 My biggest measured limitation right now: Research engine + knowledge store: keyword overl
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
  - #-9999908 My biggest measured limitation right now: Autonomy: no research or self-modification objec
  - #-9999907 My biggest measured limitation right now: Autonomy: lessons are derived strings, not model
  - #-9999906 My biggest measured limitation right now: Autonomy: one task per cycle, no parallel object
  - #-9999943 My biggest measured limitation right now: `present` failed 2 of its last 11 uses (18%). Im
  - #-9999905 Build the GPU probe you proposed on 2026-10-07 (objective 88): add `gpu()` to backend/syra
  - #-9999901 Learn how to do what objective #96 could not: `release` failed 3 of its last 5 uses (60%).
  - #-9999899 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #-9999898 Learn how to do what objective #100 could not: `release` failed 3 of its last 5 uses (60%)
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
  - #-9999946 My biggest measured limitation right now: `present` failed 2 of its last 11 uses (18%). Im
  - #-9999910 My biggest measured limitation right now: Self-model: no historical performance/latency me
  - #-9999911 My biggest measured limitation right now: Self-model: system_map.json is hand-audited and 
  - #-9999909 My biggest measured limitation right now: Self-model: does not yet feed an objectives engi

## 2026-10-07

- Tasks: 3 finished, 0 failed (235 journal events).
- Objectives closed: 3
  - #-9999914 My biggest measured limitation right now: Journal: PENDING tasks are stored but not schedu
  - #-9999913 My biggest measured limitation right now: Journal: maintenance never deletes tasks, knowle
  - #-9999912 My biggest measured limitation right now: Self-model: GPU is not probed. Improve it. Plan:

## 2026-10-06

- Tasks: 3 finished, 0 failed (226 journal events).
- Objectives closed: 3
  - #-9999917 My biggest measured limitation right now: Core: one task at a time; no queue scheduling. I
  - #-9999916 My biggest measured limitation right now: Core: brain events from a running task are journ
  - #-9999915 My biggest measured limitation right now: Journal: only file edits are reality-checked; ot

## 2026-10-05

- Tasks: 24 finished, 1 failed (830 journal events).
- Objectives closed: 13
  - #-9999933 My biggest measured limitation right now: Frontend HUD: history/today views are polled on 
  - #-9999932 My biggest measured limitation right now: 6 of 17 brain calls in the last 24 h failed over
  - #-9999930 Learn how to do what objective #69 could not: `browser_exec` failed 4 of its last 13 uses 
  - #-9999928 Learn how to do what objective #71 could not: `browser_exec` failed 4 of its last 13 uses 
  - #-9999926 2 objectives about the `browser_exec` tool are BLOCKED after repeated failures. Research a
  - #-9999925 3 objectives about the `browser_exec` tool are BLOCKED after repeated failures. Research a
  - #-9999924 My biggest measured limitation right now: `python_execute` failed 8 of its last 40 uses (2
  - #-9999923 My biggest measured limitation right now: Frontend HUD: HUD regions (orb, controls, consol

## 2026-10-04

- Tasks: 3 finished, 0 failed (253 journal events).
- Objectives closed: 3
  - #-9999936 My biggest measured limitation right now: Journal: maintenance never deletes tasks, knowle
  - #-9999935 My biggest measured limitation right now: Self-model: GPU is not probed. Improve it. Plan:
  - #-9999934 My biggest measured limitation right now: Self-model: system_map.json is hand-audited and 

## 2026-10-03

- Tasks: 94 finished, 0 failed (1746 journal events).
- Objectives closed: 19
  - #-9999958 My biggest measured limitation right now: Core: brain events from a running task are journ
  - #-9999956 Learn how to do what objective #43 could not: Task quality regressed to 78.6% (-21.4 pp); 
  - #-9999954 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #-9999953 Learn how to do what objective #45 could not: Task quality regressed to 78.6% (-21.4 pp); 
  - #-9999951 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #-9999957 Task quality regressed to 78.6% (-21.4 pp); failing cases: restraint, research_cite, act_d
  - #-9999955 Task quality regressed to 78.6% (-21.4 pp); failing cases: restraint, research_cite, act_d
  - #-9999950 Quality case `act_delete` failed in the last two runs (file old.log removed → still there)
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

- Tasks: 97 finished, 0 failed (1641 journal events).
- Objectives closed: 22
  - #-9999979 Quality case `research_cite` failed in the last two runs (tool research used → tools: ['kn
  - #-9999979 Quality case `research_cite` failed in the last two runs (tool research used → tools: ['kn
  - #-9999977 The `python_execute` tool failed on its last use. Diagnose why, then call it again with a 
  - #-9999976 My biggest measured limitation right now: 157 of 471 brain calls in the last 24 h failed o
  - #-9999973 My biggest measured limitation right now: `python_execute` failed 26 of 108 uses (24%). Im
  - #-9999978 Quality case `self_version` failed in the last two runs (final matches faa5867 → Done.). R
  - #-9999972 My biggest measured limitation right now: Frontend HUD: history/today views are polled on 
  - #-9999971 My biggest measured limitation right now: Frontend HUD: HUD regions (orb, controls, consol
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

- Tasks: 66 finished, 21 failed (1006 journal events).
- Objectives closed: 20
  - #-9999999 Verify that the `browser_exec` tool works on this machine by calling it with a harmless, r
  - #-9999998 Verify that the `browser_screenshot` tool works on this machine by calling it with a harml
  - #-9999997 Verify that the `desktop` tool works on this machine by calling it with a harmless, read-o
  - #-9999996 Verify that the `know` tool works on this machine by calling it with a harmless, read-only
  - #-9999995 Verify that the `python_execute` tool works on this machine by calling it with a harmless,
  - #-9999994 Verify that the `recall` tool works on this machine by calling it with a harmless, read-on
  - #-9999993 Verify that the `research` tool works on this machine by calling it with a harmless, read-
  - #-9999992 Verify that the `skill_list` tool works on this machine by calling it with a harmless, rea
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
