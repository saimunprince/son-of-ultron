# SYRAX Gap Analysis (audit of 2026-09-26, updated after the foundation commit)

Legend: EXISTS · PARTIAL · MISSING · NEEDS REFACTOR · NEEDS REPLACEMENT.
Every row names the code that backs the verdict; nothing is claimed from docs.

| Capability (vision §) | Verdict | Where / why |
|---|---|---|
| Agent core (think/act loop, tools) | EXISTS | `app/agent/*`, `syrax/agent.py` |
| Multi-provider brain with failover | EXISTS | `syrax/brains.py` (`BrainRouter`) |
| Long-term facts + recent history in prompt | EXISTS | `syrax/memory.py` (flat JSON/JSONL) |
| Voice, browser, desktop tools | EXISTS | `syrax/voice.py`, `browser.py`, `desktop.py` |
| Live WS stream | EXISTS | `syrax/server.py` |
| **Durable execution journal (§13, §15)** | EXISTS (this commit) | `syrax/journal.py`: SQLite WAL, transactional |
| **Task lifecycle with enforced transitions (§11)** | EXISTS (this commit) | `journal.py` `TRANSITIONS`, `_apply` |
| **Semantic checkpoints with working context (§5)** | EXISTS (this commit) | `journal.checkpoint`, `SyraxAgent.act/export_context` |
| **Crash detection + reality verification (§14)** | EXISTS (this commit) | `recover_interrupted`, `verify_operation` (file edits only) |
| **Resume from checkpoint (§3)** | PARTIAL | manual `resume` + optional auto-resume of RESUMABLE; UNCERTAIN never auto-resumed |
| **Core independent of UI (§13, §14)** | EXISTS (this commit) | `syrax/core.py`; sessions are observers |
| **Event stream = single source of truth (§6, §33)** | EXISTS (this commit) | journal fan-out → sessions; history/task_events over WS |
| **Verification gate with evidence (§8, §25)** | EXISTS (this commit) | `syrax/verify.py`, `verifications` table |
| Truthful states (§7, §12) | EXISTS (this commit) | status enum, `final`-required guard, `unjournaled` flag, NOT_VERIFIED gates |
| System map / self-model (§5, §10) | EXISTS (self-model commit) | `syrax/selfmodel.py` merges `docs/system_map.json`, repo/git, journal and runtime; capability registry derived from evidence |
| Self-understanding engine (§6) | PARTIAL | `self_inspect` tool + WS `self_model` + `/self` answer what/version/tools/failed/weakness from evidence; no natural-language reasoning layer beyond the LLM reading the snapshot |
| Objectives (§17) | EXISTS (autonomy commit) | `objectives` table, transitions, derivation from self-model weaknesses, human objectives over WS |
| Research / learning / knowledge store (§7, §8) | EXISTS (research commit) | `syrax/research.py` + `knowledge` table: search → fetch → excerpts → provenance + confidence policy; `learn` capped by evidence; failure → research objective. Knowledge → skill/tool progression not yet |
| Skill / tool / module factory (§9) | EXISTS (skills commit) | `syrax/skills.py`: code + tests → subprocess pytest → registry → live tool; metadata (name, purpose, version, dependencies, tests, status, limitations, last_verified); boot re-registration. Module-level generation and auto-commit not yet |
| Autonomous coding loop with rollback (§10, §41) | MISSING | gate exists; no agent-driven change pipeline |
| Failure-driven learning (§11) | PARTIAL | objectives retry with a derived lesson, block after 3 attempts; no strategy search or research yet |
| 24/7 cycle + resource awareness (§16, §19) | PARTIAL | `Autonomy.loop` with interval, CPU/RAM gate, idle when nothing to do; off by default; no GPU/disk/network awareness |
| Presentation engine / visual runtime (§22–30) | MISSING | static HUD in `components/Syrax.tsx` |
| LIVE / HISTORY / WHY observer (§31–35) | EXISTS (observer commit) | console tabs LIVE / HISTORY / TODAY; WHY view per task from `task_detail` (events, checkpoints, objective, lesson); TODAY replay generated from `events_between` — no synthesised lines |
| Memory layers (§37) | NEEDS REFACTOR | flat `memory.json`/`history.jsonl`; history now derivable from `tasks` |
| Model interface (§20) | EXISTS | `BrainRouter` already abstracts providers |

## Roadmap mapped to files (next phases)

1. ~~Self-model (Phase 3)~~ — done: `syrax/selfmodel.py`, `self_inspect`, WS `self_model`, `/self`, SELF panel.
2. ~~Objectives + bounded autonomous loop (Phase 5)~~ — done: `syrax/autonomy.py`, see `docs/AUTONOMY.md`.
3. ~~LIVE / HISTORY / WHY view (Phase 11)~~ — done: `frontend/components/HistoryView.tsx`, WS `task_detail`, `replay`.
4. ~~Research + knowledge store (Phase 6)~~ — done: `syrax/research.py`, see `docs/RESEARCH.md`.
5. ~~Skill factory (Phase 7)~~ — done: `syrax/skills.py`, see `docs/SKILLS.md`.
6. **Autonomous development (Phase 8)** — inspect → modify → gate → commit with rollback, generated skills committed only through `verify.run_gates`.
