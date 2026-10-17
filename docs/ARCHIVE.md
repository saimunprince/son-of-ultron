# SYRAX archive

Generated 2026-10-17 10:49 +0600 by the daily ledger at commit `09e97df`, from the journal's `archive` table: every release attempt SYRAX made to its own code, the commit it started from, the commit it produced, and the quality score measured at that commit. Parent selection (Darwin Gödel Machine style) favours a high score and penalises an ancestor that already has many children. Nothing here is typed by hand.

- Variants committed: 6; attempts that did not land: 29; scored: 0.
- Best parent now: `09e97df` (newest committed variant; no quality run has scored it yet).
- Lineage of the running build: `09e97df`

| when | decision | parent → head | score | children | weight | objective | summary |
|---|---|---|---|---|---|---|---|
| 2026-10-17 10:36 | COMMITTED | `60dbf24` → `09e97df` | - | 0 | 0.000 | #267 | Add ms timing to BrainRouter.ask_tool answered events |
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
