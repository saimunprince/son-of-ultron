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
| Brain reachable without a key | PARTIAL | Pollinations anonymous: plain chat only (402 on tools) — `brains.py` |
| Request fits free-tier limits (Groq 413) | PARTIAL | per-provider `max_request_tokens`, trimming, 413 retry — `brains.py`; fixed prompt still ≈ 5k tokens |
| Rollback touches only the task's own files | DONE | `devloop.owned_files` |
| Capabilities VERIFIED from evidence on this machine | TODO | journal was reset by the OS wipe; needs a key and supervised cycles |
| `str_replace_editor` reliability | TODO | measure failure rate from `tool_stats`, then fix |
| desktop / CPU failures | TODO | re-check on Windows once cycles run |
| Quality benchmark clean | TODO | `quality.py`, 10 cases, per brain |
| Autonomous cycle reliability, resource usage, regressions | TODO | `autonomy_status`, `bench.py` |

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

- TODO: objectives carry a `plan` (ordered steps with their own checks) and an `evaluation` (what "better" means, measured).
- TODO: priority computed from evidence (impact × confidence × cost), not a constant.
- TODO: closing an objective derives the next one from what was learned.

## Phase 2 — Real self-improvement loop

"What is my biggest limitation right now?" → research → learn → experiment →
build → test → benchmark → better? keep : diagnose → new strategy.

- TODO: strategy fingerprints in the journal; the same strategy that failed the same way is never retried blindly (today: BLOCKED after 3 attempts, no fingerprint).
- PARTIAL: experiments and benchmarks exist (`experiments.py`, `bench.py`, `versions.py`).

## Phase 3 — Skill evolution

Repeated task → pattern → "this should be a skill" → design → implement →
tests → benchmark → register → observe real use → improve.

- PARTIAL: `skill_create` with tests deciding registration (`skills.py`).
- TODO: repeated-task detection from the journal; skill versions with real-use metrics.

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
- TODO: experience retrieval before planning; embeddings; contradiction handling.

## Phase 6 — Technology radar

New models, frameworks, libraries, research, agent architectures, browser and
local-inference technology, hardware → relevant? → research → experiment →
benchmark → adopt / reject.

## Phase 7 — Multi-brain intelligence

Router picks a brain per kind of work (reasoning, coding, research) and a
synthesizer merges results. Later: learn → experiment → fine-tune / distill →
specialised models.

- PARTIAL: ten providers with failover, `compare_brains` (`brains.py`).

## Phase 8 — Dynamic presentation 2.0

Intent + state + context + importance + user attention + history →
show / hide / replace / expand / minimise / voice-only / full-screen.

- PARTIAL: `presentation.py`, `Stage.tsx`, dismissal learning.

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
