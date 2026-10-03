# SYRAX Roadmap — the Next Evolution

The order below is the owner's plan (2026-09-30) and is followed as written:
each phase starts only when the one before it is GREEN with evidence. SYRAX
may read this file (`self_inspect`, `str_replace_editor view`) when it derives
its own objectives.

**Mission.** SYRAX is open source. Its job is to improve itself and to help its
human. It learns from its mistakes, knows and understands itself from its own
evidence, and when asked for something it cannot do yet, it learns it, builds
it into itself, verifies it, and then helps.

**Philosophy shift.**

> OLD: "I have tools, so I can do things."
> NEW: "I have a goal. If I lack a capability, I will discover what I need,
> learn it, build it, test it, and integrate it."

**The ultimate loop.**

```
SELF MODEL → "What is missing?" → OBJECTIVE → RESEARCH → LEARN → EXPERIMENT
→ BUILD / MODIFY → VERIFY → BENCHMARK → improved? KEEP & LEARN : DIAGNOSE
→ UPDATE SELF → NEXT OBJECTIVE → ∞
```

Legend: **DONE** · **PARTIAL** (a first real implementation exists) · **TODO**.

---

## Phase 0 — Make the current system truly GREEN

Harden what exists before building a new intelligence layer.

```
Self-model → weakness → failure (editor / desktop / …) → research → fix
→ experiment → quality_run → release gate → GREEN
```

| Item | State | Evidence / where |
|---|---|---|
| Release gate GREEN on the current machine | DONE | Windows port 2026-09-30, `python syrax.py --gate` |
| Runs anywhere with one command | DONE | `syrax.py` (Windows, Linux, macOS) |
| Brains that answer on free tiers | DONE | Gemini `3.5-flash-lite` (free keys get ~20 requests per model), Upstage `solar-pro3`, Groq with per-request token budget, clipping of big turns and MCP manuals, 402/413/parse-failure retries — `brains.py` |
| Brain reachable without any key | PARTIAL | Pollinations anonymous rejects tools, temperature, large `max_tokens` and prompts over ~1000 words: plain chat only |
| Rollback touches only the task's own files | DONE | `devloop.owned_files` |
| One live owner per journal | DONE | OS lock on `journal.db.owner`; a second core cannot recover live tasks |
| Core jobs survive a closed tab | DONE | quality runs, brain comparisons and forced cycles are detached jobs |
| SYRAX can find itself | DONE | `self_inspect(task_id=…)`, `repo_root` in identity, absolute paths in the autonomous brief |
| Capabilities VERIFIED from evidence on this machine | DONE | 14 tools used successfully; `release`, `skill_*`, `experiment` await real use |
| Final replies carry the answer | DONE | own step prompt (no undo loops); wrap-up call when a model terminates silently |
| Quality benchmark clean | DONE | 20 → 30 → 70 → 80 → 50 → 90 → 90 % (runs 1–8; run 6 came from a stray second core and is not a real baseline) |
| `str_replace_editor` reliability | TODO | 22 ok / 11 failed so far: relative paths (brief fixed), missing `path`, wrong indentation in `old_str`, `create` on an existing file, bad `view_range` |
| `research` when explicitly asked | TODO | research_cite answers correctly from `know` but skips `research`; left for SYRAX's own objective loop |
| Autonomous cycle reliability | PARTIAL | 22 cycles ran, 2 skipped for RAM, no crash; 19 objectives DONE, 3 OPEN |

**Exit criterion:** every non-exempt capability VERIFIED or explained, gate
GREEN, one quality run ≥ 90 % on the primary brain, 20 autonomous cycles with
no crash.

## Phase 1 — Autonomous Objective Engine 2.0

Today: `weakness → objective → one task → judge` (`autonomy.py`). Target:

```
Observe → Understand → Detect need → Create objective → Prioritize → Plan
→ Execute → Verify → Learn → Update self → Evaluate objective → Next objective
```

SYRAX manages its own development agenda, not single tasks.

- DONE (2026-10-01): when nothing is open, `syrax/limits.py` ranks SYRAX's limitations from journal counts (tool failure rate × volume, brain failover share, known limitations) and turns the strongest into an objective with a four-step plan and a measurable check (`tool_reliability`: new uses only). The ranking is journaled (`limitation.ranked`). First live loops closed: python_execute reliability (#27) DONE; brain failover research (#24) DONE.
- DONE: Verify step — a quality objective with an attempt behind it is measured by the cycle itself; BLOCKED objectives with a machine check close when later evidence satisfies them.
- DONE: the brief carries the objective's evidence (recent failures, counts), so SYRAX reads them instead of guessing journal tables.
- DONE (2026-10-01): plans with per-step checks (`syrax/plan.py`). Each doing step of a limitation plan carries a machine check (`tool_ok`, `released`, `learned`) proven from the journal across the objective's attempts. The brief shows DONE / NEXT / TODO, a retry resumes at the first unproven step (`next_action`), `plan.progressed` is journaled, and an attempt that proves new steps is progress, not a blind repeat.
- DONE (2026-10-01): the next objective comes from what the last one taught (`syrax/followup.py`). A BLOCKED objective that released a change gets a follow-up told which commits missed and which failures came after them. One that neither released nor learned anything first gets a learning objective (research → learn), then a retry that depends on it and is briefed with what was learned. Depth-capped, once per objective, journaled as `followup.derived`.

- DONE: SYRAX restarts itself (idle, launched by syrax.py) when a commit it has not loaded is on disk, so a released fix takes effect without a human.
- DONE: limitation priority = score × confidence ÷ cost, each measured per kind from the journal.
- DONE: researched limitations end in proposals for the human (`proposals`); the OpenRouter key came from one.

### Compared with Brahma AI Evo (2026-10-01)

Brahma (Windows desktop AI) forges skills into `features/`, tests them in a sandbox and hot-reloads them, and its Auto-Heal patches running code from a traceback without a gate. SYRAX keeps the gate (it tried to game its judge twice today) and restarts into code that passed it. Worth taking as ideas, not code (its license is personal-use only): Windows window control (list/focus/tile), Office documents as skills SYRAX builds itself (a Phase 3 test), and low-latency native-audio voice later.

### Integrity rules learned on 2026-10-01

Working its own objectives, SYRAX twice reached for its judge instead of its behaviour: it weakened a quality case's check (`research` → `know`), and it ran an edited copy of the case in a second core it built in python_execute, storing a "pass" that closed the objective. What now stands between an agent and its judge:

- autonomous `release` refuses the judge and guard files (quality, verify, bench, autonomy, experiments, versions, devloop, limits, journal, guard, tools) and edits to existing tests;
- only the process that owns the journal (OS lock) writes it; any other opens read-only;
- code run by python_execute, and every Python it starts, cannot write the journal or the brain keys;
- a human can reopen an objective closed on bad evidence (`objective_update`, journaled as `objective.reopened`).

These are guard rails against the paths SYRAX actually took, not a sandbox; they make each improvement it reports real.

## Phase 2 — Real self-improvement loop

"What is my biggest limitation right now?" → research → learn → experiment →
build → test → benchmark → better? keep : diagnose → new strategy.

- TODO: strategy fingerprints in the journal; the same strategy that failed the same way is never retried blindly (today: BLOCKED after 3 attempts, no fingerprint).
- PARTIAL: experiments and benchmarks exist (`experiments.py`, `bench.py`, `versions.py`).

## Phase 3 — Skill evolution

Repeated task → pattern → "this should be a skill" → design → implement →
tests → benchmark → register → observe real use → improve.

- PARTIAL: `skill_create` with tests deciding registration (`skills.py`).
- DONE (2026-10-03): skills evolve from real use (`syrax/skillevo.py`). Every skill call is counted since its version was verified (shown in the MIND panel); a skill failing ≥30 % of ≥3 real uses ranks as a `skill_repair` limitation: reproduce the failure as a new test, then a new version that passes old and new tests (check: `skill_verified`).
- DONE (2026-10-03): repeated-task detection. Human requests that recur 3+ times in 14 days, solved with the same working tools and not covered by a skill, become a `skill_candidate` proposal (daily, with the radar). SYRAX proposes; it does not build skills nobody asked for.

## Phase 4 — Self-modification 2.0

"I need a capability" → which module, why, what depends on it, what could
break, which tests prove it, which benchmark should move, where the rollback
point is → inspect → design → modify → test → benchmark → regression →
release → update self-model. Evidence-driven engineering, not random rewriting.

- PARTIAL: `release` = gate → commit or rollback (`devloop.py`); push stays with the human unless `SYRAX_AUTOPUSH=1`.
- TODO: a change plan recorded before editing (module, dependents from `system_map.json`, tests, target benchmark).

## Phase 5 — Long-term memory / experience

Working → episodic → knowledge → skills → lessons → self-knowledge →
long-term experience. "Three weeks ago this approach performed badly because
of X, so this time I use Y."

- PARTIAL: journal (tasks, checkpoints, knowledge, lessons, facts).
- DONE (2026-10-01): experience retrieval before planning: every autonomous brief carries the closed objectives most like this one, with what worked or why they failed (`past_experience`).
- DONE (2026-10-03): knowledge consolidates (`syrax/consolidate.py`). A conclusion that matches a stored one is reinforced, not stored again (SQLite's release year had been stored four times); one about the same subject with different figures is stored, flagged as `knowledge.contradiction`, shown as DISPUTED by `know`, and turned into an objective to settle it with fresh research.
- TODO: embeddings, when a local embedding model is worth its dependency; keyword overlap decides "same subject" today.

## Phase 6 — Technology radar

New models, frameworks, libraries, research, agent architectures, browser and
local-inference technology, hardware → relevant? → research → experiment →
benchmark → adopt / reject.

- DONE (2026-10-01): new models on SYRAX's own brains, tool-call tested, proposed (`radar.py`).
- DONE (2026-10-03): SYRAX's own dependencies. The daily radar pass runs `npm audit` on the UI; a new critical or high advisory becomes a `security` proposal (once per finding). It started from a manual audit that found a critical Windows RCE in next 16.2.10 (fixed in 225e21d). Python dependencies too: the installed packages are checked against OSV.dev (GitHub and PyPA advisories) with each one's worst severity and the version that fixes it; no extra tool needed. First run, 2026-10-03: 14 vulnerable, 3 critical (crawl4ai, litellm, transformers), 7 high (lxml, mcp, nltk, pillow, setuptools, starlette, text-generation).

## Phase 7 — Multi-brain intelligence

Router picks a brain per kind of work (reasoning, coding, research) and a
synthesizer merges results. Later: learn → experiment → fine-tune / distill →
specialised models.

- PARTIAL: ten providers with failover, `compare_brains` (`brains.py`).
- DONE (2026-10-03): routing by kind of work (`syrax/routing.py`). Each task is classified (chat, code, research, desktop, other); graded quality runs give each brain's quality per kind. A brain is tried first for a kind only when it and the human's first brain both have 5+ graded tasks of that kind and it is 15+ points better; otherwise the human's order stands. Journaled as `brain.routed`; the MIND panel shows the per-kind evidence.
- TODO: a synthesizer that merges several brains' answers.

## Phase 8 — Dynamic presentation 2.0

Intent + state + context + importance + user attention + history →
show / hide / replace / expand / minimise / voice-only / full-screen.

- PARTIAL: `presentation.py`, `Stage.tsx`, dismissal learning.
- NEXT (specified 2026-10-03, "Visible Work Presence"): a truthful live view of what SYRAX is doing — current task, phase, action, target, application — with
  visibility levels visible / minimal / hidden that never touch execution, "hide" / "show" by voice and text, a durable timeline, redaction of secrets. Needs a
  task phase model first (the `stage.started` wire event exists and is never recorded: use it for understand / plan / act / observe / verify), a
  `work_presence` state in `Core.snapshot()`, an active-window reader in `winctl.py` journaled only during desktop/browser calls, and `hello.tool_levels`
  (permissions, 2026-10-03) for the tool view. Level 3 (live workspace) mechanism is still the owner's decision.
- Reference studied 2026-10-03: jaredrhod's barehands / backtalk / ai-visualizer (all **AGPL-3.0**: ideas only, no code). Worth re-implementing: a
  read-back of the stage for the agent ("eyes on the board": zone + state per card, so SYRAX describes only what is really shown); an allow-listed command
  channel with clamped arguments for anything the model puts on stage; stale-state decay (every "thinking/working" indicator carries a timestamp and falls
  back to "unknown" when the backend stops heartbeating — never a frozen ring); scale-invariant pinch/tap/clap thresholds for `handTracker.ts`; a
  tracker/render role split (one page tracks, another renders from state), which maps onto visible / minimal / hidden. Not worth copying: free-running
  "thinking" animations and demo modes that fabricate state.

## Phase 9 — Continuous life cycle

Boot → recover → understand state → review experience → check environment →
select objective → research → work → experiment → learn → improve → reflect →
next objective; at low activity, observe the world and create new objectives.

- PARTIAL: idle cycles, resource gate, quiet hours, maintenance (`autonomy.py`, `resources.py`).

## Phase 10 — Model development (eventually)

Use existing LLMs → understand architecture → collect training data →
experiment with small models → specialised model → fine-tuning →
distillation → own inference stack → own model research. Bounded by hardware,
data and compute; the architecture stays open to it.

---

## Immediate order

1. Current verification BLOCKED → GREEN (done on Windows)
2. `str_replace_editor` reliability
3. desktop / CPU failures
4. Quality benchmark clean
5. Autonomous Objective Engine 2.0
6. Self-improvement loop
7. Skill evolution
8. Experience / long-term memory
9. Technology radar
10. Multi-brain routing
11. Dynamic presentation evolution
12. Continuous autonomous life cycle
13. Own model development
