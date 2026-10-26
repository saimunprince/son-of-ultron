# SYRAX archive

Generated 2026-10-26 12:20 +0600 by the daily ledger at commit `ce024ca`, from the journal's `archive` table: every release attempt SYRAX made to its own code, the commit it started from, the commit it produced, and the quality score measured at that commit. Parent selection (Darwin Gödel Machine style) favours a high score and penalises an ancestor that already has many children. Nothing here is typed by hand.

- Variants committed: 25; attempts that did not land: 47; scored: 4.
- Best parent now: `e2c362a` (score 88% with 0 child(ren): weight 0.979).
- Lineage of the running build: `d723e7c`

| when | decision | parent → head | score | children | weight | objective | summary |
|---|---|---|---|---|---|---|---|
| 2026-10-25 12:05 | COMMITTED | `0ab288e` → `d723e7c` | - | 0 | 0.000 | - | docs(rise): the ledger, the devlog and the capability matrix, regenera |
| 2026-10-22 16:57 | COMMITTED | `70f38e8` → `bc736e2` | - | 0 | 0.000 | #309 | Fix capability implementation paths in backend/syrax/selfmodel.py and  |
| 2026-10-22 16:43 | REFUSED | `70f38e8` → `-` | - | 0 | 0.000 | #309 | Fix capability implementation paths in backend/syrax/selfmodel.py for  |
| 2026-10-22 16:43 | REFUSED | `70f38e8` → `-` | - | 0 | 0.000 | #309 | Fix self_inspect capability mappings for editor, journal_query, remind |
| 2026-10-22 16:43 | REVIEW_REJECTED | `70f38e8` → `-` | - | 0 | 0.000 | #309 | Fix self_inspect capability mappings for editor, journal_query, remind |
| 2026-10-22 16:25 | REFUSED | `70f38e8` → `-` | - | 0 | 0.000 | #309 | Fix capability paths in selfmodel and add test_capability_files.py |
| 2026-10-22 13:21 | COMMITTED | `c6e684c` → `3d05189` | - | 0 | 0.000 | #306 | Fix covering_tests to correctly handle map path entries and protect to |
| 2026-10-22 12:45 | COMMITTED | `9a9b640` → `01ea7f1` | - | 0 | 0.000 | - | docs(rise): the ledger, the devlog and the capability matrix, regenera |
| 2026-10-19 13:32 | COMMITTED | `0ab1705` → `c476788` | - | 0 | 0.000 | #298 | Expand negation check in named_tools to cover more words and character |
| 2026-10-19 13:18 | REFUSED | `0ab1705` → `-` | - | 0 | 0.000 | #294 | Dummy release for workspace check |
| 2026-10-19 13:18 | REFUSED | `0ab1705` → `-` | - | 0 | 0.000 | #294 | Improve python_execute robustness against subprocess communication err |
| 2026-10-19 13:12 | COMMITTED | `83c2dd3` → `0ab1705` | - | 3 | 0.000 | #296 | Allow LearnTool to accept sources cited as knowledge_id=536 or id=536. |
| 2026-10-19 12:47 | REFUSED | `aa66fbb` → `-` | - | 0 | 0.000 | #288 | Improve python_execute robustness against timeouts and process errors |
| 2026-10-19 12:42 | COMMITTED | `ad9cd44` → `aa66fbb` | - | 1 | 0.000 | #292 | Fix apply_patch to detect and correct undercounted hunk headers. |
| 2026-10-19 12:29 | COMMITTED | `7450f07` → `ad9cd44` | - | 1 | 0.000 | #291 | Fix table header argument handling and _clip function to correctly dis |
| 2026-10-19 12:20 | REFUSED | `7450f07` → `-` | - | 0 | 0.000 | #291 | Fix table header argument handling and _clip function to correctly dis |
| 2026-10-19 12:16 | COMMITTED | `92f3936` → `7450f07` | - | 2 | 0.000 | #290 | Mask credentials in final answers unless requested by the human |
| 2026-10-19 12:06 | REFUSED | `92f3936` → `-` | - | 0 | 0.000 | #290 | Mask credentials in final answers unless requested by the human |
| 2026-10-19 12:06 | REFUSED | `92f3936` → `-` | - | 0 | 0.000 | #290 | Mask credentials in final answers unless requested by the human |
| 2026-10-19 12:06 | REFUSED | `92f3936` → `-` | - | 0 | 0.000 | #290 | Mask credentials in final answers unless requested by the human |
| 2026-10-19 12:06 | REFUSED | `92f3936` → `-` | - | 0 | 0.000 | #290 | Mask credentials in final answers unless requested by the human |
| 2026-10-19 12:03 | COMMITTED | `c678a48` → `92f3936` | - | 5 | 0.000 | #289 | Require new_str in str_replace to prevent accidental file-emptying whe |
| 2026-10-19 11:27 | COMMITTED | `a26aae2` → `2431cec` | - | 0 | 0.000 | #282 | Editor: missing file reports close names using difflib sequence matche |
| 2026-10-19 11:07 | COMMITTED | `7c55302` → `a26aae2` | 100% | 1 | 0.497 | #285 | Prevent named_tools from matching forbidden or negated tools (e.g. Do  |
| 2026-10-19 10:48 | REFUSED | `7c55302` → `-` | - | 0 | 0.000 | #283 | Update TEST_TIMEOUT_S to 400 in backend/syrax/selfedit.py |
| 2026-10-19 10:43 | REFUSED | `7c55302` → `-` | - | 0 | 0.000 | #283 | Update TEST_TIMEOUT_S to 400 in backend/syrax/selfedit.py. |
| 2026-10-19 10:34 | COMMITTED | `9798b6e` → `7c55302` | 75% | 3 | 0.231 | #280 | Fix apply_patch test reporting when no tests ran and update ApplyPatch |
| 2026-10-17 16:12 | COMMITTED | `1881bb2` → `56dc711` | 86% | 0 | 0.974 | #276 | Editor: a worktree path to an untracked file reads the running tree. |
| 2026-10-17 15:48 | COMMITTED | `c92f74e` → `c6342ec` | - | 0 | 0.000 | #275 | Add SLEEP_GAP_S to stallwatch watchdog to prevent false stall reports  |
| 2026-10-17 15:14 | COMMITTED | `5218b36` → `0b42181` | - | 0 | 0.000 | #274 | Add memory subject matching and contradiction replacement in MemorySto |
| 2026-10-17 14:59 | ROLLED_BACK | `5218b36` → `-` | - | 0 | 0.000 | #274 | Add memory subject matching and contradiction replacement in MemorySto |
| 2026-10-17 13:15 | COMMITTED | `31d59e2` → `5218b36` | - | 2 | 0.000 | #273 | Add Running build headline to self_inspect output when identity has a  |
| 2026-10-17 11:51 | COMMITTED | `0ab202d` → `e2c362a` | 88% | 0 | 0.979 | #272 | Add brain_ms performance metric to SelfModel and test_brain_ms.py |
| 2026-10-17 11:36 | REFUSED | `0ab202d` → `-` | - | 0 | 0.000 | #271 | Add brain_ms calculation to SelfModel.performance() and test_brain_ms. |
| 2026-10-17 11:36 | REFUSED | `0ab202d` → `-` | - | 0 | 0.000 | #271 | Add brain_ms calculation to SelfModel.performance() and test_brain_ms. |
| 2026-10-17 11:35 | REFUSED | `0ab202d` → `-` | - | 0 | 0.000 | #271 | Add brain_ms calculation to SelfModel.performance() and test_brain_ms. |
| 2026-10-17 11:07 | COMMITTED | `09e97df` → `b46c45f` | - | 0 | 0.000 | - | docs(rise): the ledger, the devlog and the capability matrix, regenera |
| 2026-10-17 10:36 | COMMITTED | `60dbf24` → `09e97df` | - | 1 | 0.000 | #267 | Add ms timing to BrainRouter.ask_tool answered events |
| 2026-10-15 18:24 | REFUSED | `9932b91` → `-` | - | 0 | 0.000 | #266 | Add brain latency metrics to SelfModel and brain answered events. |
| 2026-10-15 18:11 | REFUSED | `92c3bd1` → `-` | - | 0 | 0.000 | #266 | Use Journal.emit in test_brain_ms.py |
| 2026-10-15 18:09 | REFUSED | `92c3bd1` → `-` | - | 0 | 0.000 | #266 | Fix Journal method calls in test_brain_ms.py |
| 2026-10-15 18:08 | REFUSED | `92c3bd1` → `-` | - | 0 | 0.000 | #266 | Fix test_brain_ms.py test function with sync run wrapper |
| 2026-10-15 18:06 | REFUSED | `92c3bd1` → `-` | - | 0 | 0.000 | #266 | Add brain_ms metric and test_brain_ms.py |
| 2026-10-15 18:04 | REFUSED | `92c3bd1` → `-` | - | 0 | 0.000 | #266 | Fix test_brain_ms.py listener set append method |
| 2026-10-15 18:02 | REFUSED | `92c3bd1` → `-` | - | 0 | 0.000 | #266 | Add brain_ms latency metrics to SelfModel and ms duration to brain ans |
| 2026-10-15 17:49 | COMMITTED | `0045643` → `92c3bd1` | - | 6 | 0.000 | #262 | Add tool_ms performance metrics to SelfModel and test suite |
| 2026-10-15 17:25 | COMMITTED | `f32efc2` → `162fd71` | - | 0 | 0.000 | #252 | Add task_seconds aggregation to SelfModel.performance() grouped by tas |
| 2026-10-15 17:05 | COMMITTED | `5a9f490` → `f32efc2` | - | 1 | 0.000 | #249 | Self-model: Probe GPU using sysinfo.gpu() and cache the result |
| 2026-10-15 16:33 | REFUSED | `e80a764` → `-` | - | 0 | 0.000 | #249 | Self-model: Probe GPU using sysinfo.gpu() and cache the result |
| 2026-10-15 16:33 | REFUSED | `e80a764` → `-` | - | 0 | 0.000 | #249 | Self-model: Probe GPU using sysinfo.gpu() and cache the result |
| 2026-10-15 16:32 | REFUSED | `e80a764` → `-` | - | 0 | 0.000 | #249 | Self-model: Probe GPU using sysinfo.gpu() and cache the result |
| 2026-10-15 16:32 | REFUSED | `e80a764` → `-` | - | 0 | 0.000 | #249 | Self-model: Probe GPU using sysinfo.gpu() and cache the result |
| 2026-10-15 16:08 | COMMITTED | `99e62a5` → `6afccd1` | - | 0 | 0.000 | #247 | Memory expiry for observations older than 30 days in MemoryStore.promp |
| 2026-10-15 12:56 | REVIEW_REJECTED | `58aef24` → `-` | - | 0 | 0.000 | #237 | Implement memory expiry for observations older than 30 days. |
| 2026-10-15 11:53 | REFUSED | `3711e87` → `-` | - | 0 | 0.000 | #232 | Implement memory expiry for observations older than 30 days. |
| 2026-10-15 11:51 | REFUSED | `3711e87` → `-` | - | 0 | 0.000 | #232 | Implement memory expiry for observations older than 30 days. |
| 2026-10-15 11:40 | REFUSED | `0389893` → `-` | - | 0 | 0.000 | #234 | Update Pydantic .dict() to .model_dump() in app/schema.py. |
| 2026-10-15 11:21 | REFUSED | `006d38b` → `-` | - | 0 | 0.000 | #232 | Implement memory expiry for observations older than 30 days. |
| 2026-10-15 11:18 | ROLLED_BACK | `006d38b` → `-` | - | 0 | 0.000 | #232 | Implement memory expiry for observations older than 30 days. |
| 2026-10-15 10:46 | COMMITTED | `b3be3c2` → `e6f0ed3` | - | 0 | 0.000 | - | docs(rise): the ledger, the devlog and the capability matrix, regenera |
| 2026-10-14 19:24 | ROLLED_BACK | `5939de9` → `-` | - | 0 | 0.000 | #224 | Implement 30-day expiry for inferred observations in the system prompt |
| 2026-10-14 17:27 | REFUSED | `-` → `-` | - | 0 | 0.000 | #217 | Restore README.md title. |
| 2026-10-14 17:25 | COMMIT_FAILED | `b4737d3` → `-` | - | 0 | 0.000 | #217 | Update README.md title to 'SYRAX probe'. |
| 2026-10-14 15:47 | ROLLED_BACK | `48d4d22` → `-` | - | 0 | 0.000 | #210 | Improve desktop find_files robustness when target is empty or passed a |
| 2026-10-14 15:39 | REFUSED | `-` → `-` | - | 0 | 0.000 | #210 | Improve desktop find_files robustness when target is empty or passed a |
| 2026-10-14 15:34 | REFUSED | `-` → `-` | - | 0 | 0.000 | #210 | Improve desktop.find_files to handle target in folder argument. |
| 2026-10-14 15:34 | REFUSED | `-` → `-` | - | 0 | 0.000 | #210 | Improve desktop.find_files to handle target in folder argument. |
| 2026-10-14 15:34 | REFUSED | `-` → `-` | - | 0 | 0.000 | #210 | Improve desktop.find_files to handle target in folder argument. |
| 2026-10-14 14:41 | REFUSED | `-` → `-` | - | 0 | 0.000 | #204 | Revert journal_query modification and keep clean state |
| 2026-10-14 14:30 | ROLLED_BACK | `d48f5a4` → `-` | - | 0 | 0.000 | #204 | Fix journal_query tool to correctly handle PRAGMA statements and ensur |
| 2026-10-14 14:09 | ROLLED_BACK | `d48f5a4` → `-` | - | 0 | 0.000 | #199 | Verify apply_patch with a harmless new file |
| 2026-10-14 13:51 | REFUSED | `-` → `-` | - | 0 | 0.000 | #196 | test apply_patch successfully |
