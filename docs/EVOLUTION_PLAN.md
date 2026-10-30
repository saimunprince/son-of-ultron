# SYRAX Evolution Plan — the 300 research directions, mapped and scheduled

Written 2026-10-30; rows marked "wave 1"/"wave 2" were built and pushed the same day (red test, GREEN gate). This plan takes the owner's list of 300 independent-intelligence research directions and checks
each one against the code that exists today. Every row was found by reading and grepping the repository: three
read-only audits, one per hundred items. Nothing below is a claim about plans. The status describes the code as it is
now. The waves at the end say what gets built, in what order, and how each part is proven.

**Status words**
- **EXISTS**: implemented, and a test covers it.
- **PARTIAL**: something works, but an important part is missing, or it is only a prompt sentence ("prompt only").
- **MISSING**: no code does it.
- **OUT OF SCOPE**: a local software agent on one CPU-only PC, with free-tier LLM APIs, cannot do this honestly.
  The reasons are listed below.

Paths are under `backend/syrax/` unless shown otherwise. Tests sit beside the modules (`test_*.py`).

## Summary

| Part | EXISTS | PARTIAL | MISSING | OUT OF SCOPE |
|---|---|---|---|---|
| I–II Intelligence, learning, memory (1–100) | 31 | 51 | 15 | 3 |
| III–V Self-improvement, autonomy, social, ethics (101–200) | 40 | 34 | 25 | 1 |
| VI–VII Perception, infrastructure, future (201–300) | 34 | 38 | 11 | 17 |
| **All 300** | **105** | **123** | **51** | **21** |

The counts are taken from the tables below, one status per item, as mapped on 2026-10-30. After waves 1 and 2 (built
the same day, 17 rows changed): **121 EXISTS, 112 PARTIAL, 46 MISSING, 21 out of scope.**

**What is strong:** the journal and recovery, the permissions and kernel boundary, honesty checks on answers,
emergency stop and budgets, the release gate with red-test proof, skill versioning and rollback, and knowledge with
provenance and freshness.

**What is weak:**
- calibration: stated confidence is never compared with outcomes;
- prompt-injection containment;
- desktop control on Linux: the click, keyboard and front-window code is Windows-only;
- statistics in experiments;
- emotion and theory-of-mind modeling: none exists;
- multilingual replies;
- long-running drift checks.

## Out of scope, and why

21 items cannot be built honestly on this machine. Nothing in this plan pretends otherwise.

- **No body or sensors (211–217, 220, 34):** robot locomotion, manipulation, motor control, tactile sense, balance,
  sim-to-real transfer, embodied adaptation and physical intuition. SYRAX has no robot. Human–agent interaction (216)
  is covered by voice, the HUD and `ask_human`.
- **No model weights (88, 89):** a fine-tuning pipeline and weight-evolution experiments need training access the
  free APIs do not give, and this CPU cannot train a useful model. `trajectories.py` already exports graded data in
  case that ever changes.
- **No other machines (231, 232, 233, 237):** distributed inference, federated learning, peer-to-peer coordination and
  distributed memory. There is one node. The Windows PC shares history through journal import, not live coordination.
- **One owner (165):** conflict mediation has no parties to mediate.
- **Model internals (284):** attention mechanisms live inside the hosted models; SYRAX cannot change them.
- **Consciousness (281, 287, 289, 290):** global workspace theory, consciousness theories, subjective experience and
  the ethics of sentience. These can be read about (`research`), but no code can claim to implement them. The persona
  must never claim feelings it cannot show evidence for (`claims.py` boast rules).

## Item by item

### Part I — Intelligence and cognition (1–40)

| # | Direction | Status | Evidence | Gap |
|---|---|---|---|---|
| 1 | Formal reasoning | MISSING | only python_execute arithmetic | no symbolic checker |
| 2 | Deductive reasoning | PARTIAL | brain + python_execute; claims.py checks conclusions | no rule engine |
| 3 | Inductive reasoning | PARTIAL | limits.rank, scorecard, routing.table (test_routing, test_limits_order) | counts only |
| 4 | Abductive reasoning | PARTIAL | tool_error.py classes, followup.derive | no ranked explanations |
| 5 | Causal reasoning | PARTIAL | experiments A/B, repro fail-before proof | score changes not attributed to commits (wave 2) |
| 6 | Counterfactual reasoning | MISSING | — | "what if X had not been released" (wave 2, attribution) |
| 7 | Probabilistic reasoning | PARTIAL | Laplace smoothing in routing/limits/scorecard | no probabilities on decisions |
| 8 | Constraint reasoning | PARTIAL | claims.exact_form, permissions.decide | regex constraints only |
| 9 | Analogical reasoning | PARTIAL | autonomy.past_experience | same subject only |
| 10 | Contradiction detection | EXISTS | consolidate.compare, research._dispute (test_consolidate) | figures only |
| 11 | Goal decomposition | PARTIAL | limits plan templates, plan.steps_of (test_plan) | the brain's own breakdown not stored |
| 12 | Hierarchical planning | PARTIAL | objective dependencies, followup MAX_DEPTH=2 | no goal tree |
| 13 | Long-horizon planning | PARTIAL | persistent objectives, plan.next_step | no milestones |
| 14 | Dynamic replanning | EXISTS | agent REPLAN_STREAK, strategy_of (test_replan_streak) | — |
| 15 | Resource-aware planning | EXISTS | resources.pressure, budgets (test_resources, test_controller_budgets) | no cost estimate per objective |
| 16 | Dependency mapping | PARTIAL | devloop.impact_of (hand-kept system_map.json) | no import graph |
| 17 | Risk-aware planning | EXISTS | permission and autonomy levels (test_autonomy_levels) | plan risk not scored |
| 18 | Multi-objective optimization | MISSING | single priority integer | — |
| 19 | Deadline reasoning | PARTIAL | core.TASK_DEADLINE_S (test_task_deadline) | plans ignore time left |
| 20 | Plan verification | EXISTS | plan.status, contracts.assess (test_plan, test_contracts) | — |
| 21 | Self-monitoring | EXISTS | stallwatch, loop guard, budgets (test_stallwatch, test_agent_loops) | — |
| 22 | Confidence calibration | EXISTS (wave 2: calibrate.py, test_calibration) | confidences never compared with outcomes | **wave 2** |
| 23 | Uncertainty estimation | PARTIAL | knowledge confidence, UNCERTAIN resume | answers carry none |
| 24 | Error introspection | EXISTS | tool_error.py, core error_class (test_error_class) | — |
| 25 | Strategy selection | PARTIAL | routing.preferred, strategy_of | no strategy library |
| 26 | Cognitive load management | PARTIAL | compact_tools, budgets (test_compact_tools) | no context summarizing |
| 27 | Reasoning audit | EXISTS | think events, HMAC chain, journal_query (test_journal_chain) | not critiqued |
| 28 | Assumption tracking | PARTIAL | checkpoints.assumptions column is never filled | **wave 2** |
| 29 | Blind-spot detection | PARTIAL | capmatrix UNVERIFIED rows | — |
| 30 | Metacognitive calibration | EXISTS (wave 2: calibrate.py, test_calibration) | same as 22 | **wave 2** |
| 31 | Object permanence | PARTIAL | presence.observe_window, intent ledger | no world-entity store |
| 32 | Spatial reasoning | PARTIAL | sight.py (Windows only) | wave 3 (Linux desktop) |
| 33 | Temporal reasoning | PARTIAL | clock in the prompt, knowledge age (test_clock_honesty) | no interval reasoning |
| 34 | Physical intuition | OUT OF SCOPE | — | no body |
| 35 | Social world modeling | PARTIAL | memory preference/rule types, disputes | no model of the human |
| 36 | State transition modeling | PARTIAL | phases.py, controller states | own states only |
| 37 | Environment prediction | MISSING | — | **wave 2** (tool-outcome prediction) |
| 38 | Model uncertainty | PARTIAL | UNCERTAIN recovery, capmatrix | not quantified |
| 39 | Model revision | EXISTS | knowledge supersede, memory.correct (test_knowledge_state) | — |
| 40 | Reality grounding | EXISTS | claims.py world/outcome checks (test_world_claims) | — |

### Part II — Learning and memory (41–80)

| # | Direction | Status | Evidence | Gap |
|---|---|---|---|---|
| 41 | Incremental learning | EXISTS | research learn, memory.remember (test_research) | retrieval, not weights |
| 42 | Lifelong learning | PARTIAL | durable journal + backups | no distillation |
| 43 | Online learning | PARTIAL | routing table rebuilt from quality runs | brain order only |
| 44 | Continual task adaptation | PARTIAL | past_experience, learned briefs | prompt-level |
| 45 | Catastrophic forgetting prevention | PARTIAL | quality/bench regressions, release gate | weight sense out of scope |
| 46 | Transfer learning | MISSING | lessons are recalled for the same subject only | — |
| 47 | Few-shot adaptation | PARTIAL | lessons injected into briefs | no example choice |
| 48 | Unsupervised learning | PARTIAL | skillevo.candidates groups repeated requests | — |
| 49 | Self-supervised learning | PARTIAL | trajectories.py exports graded JSONL | no consumer |
| 50 | Learning efficiency | PARTIAL | rise.py window metrics | no cost per improvement |
| 51 | Working memory | EXISTS | agent messages, checkpoint context (test_resume_fidelity) | — |
| 52 | Episodic memory | EXISTS | journal tasks/events, past_experience (test_journal) | — |
| 53 | Semantic memory | EXISTS | knowledge table, memory facts (test_research, test_memory) | keyword recall |
| 54 | Procedural memory | EXISTS | skills registry (test_skill_lifecycle) | — |
| 55 | Autobiographical memory | EXISTS | selfmodel identity, RISE ledger (test_selfmodel) | — |
| 56 | Associative retrieval | PARTIAL | word-overlap recall | wave 4 (knowledge links) |
| 57 | Memory consolidation | EXISTS | consolidate duplicates (test_consolidate) | — |
| 58 | Memory compression | PARTIAL | journal.maintain prunes chatty events | no episode summaries |
| 59 | Forgetting policy | EXISTS | observation expiry, retention (test_memory_expiry) | — |
| 60 | Memory integrity | EXISTS | HMAC chain, backup verify (test_journal_chain, test_backup) | — |
| 61 | Knowledge graph | MISSING | — | wave 4 (knowledge links) |
| 62 | Source provenance | EXISTS | source_url/excerpt, learn support check (test_learn_supports_claim) | — |
| 63 | Temporal knowledge | PARTIAL | created/verified_at, ages | no valid-from/until |
| 64 | Evidence weighting | PARTIAL | research.agreement, capped confidence | no per-source reliability |
| 65 | Conflicting-source analysis | EXISTS | consolidate.settles (test_knowledge_state) | figures only |
| 66 | Knowledge freshness | EXISTS | STALE_DAYS, knowledge_age_days (test_research_engine) | — |
| 67 | Uncertainty annotations | PARTIAL | `know` shows confidence/DISPUTED/stale | answers carry none |
| 68 | Knowledge deduplication | EXISTS | consolidate, web dedupe (test_web_dedupe) | — |
| 69 | Cross-domain integration | MISSING | — | wave 4 (knowledge links) |
| 70 | Knowledge gap mapping | PARTIAL | known limitations, research topics | — |
| 71 | Multilingual understanding | MISSING | catalog language_follow is TODO | **wave 3** |
| 72 | Contextual interpretation | PARTIAL | exact_form, context isolation (test_context_isolation) | — |
| 73 | Pragmatic reasoning | PARTIAL | exact-form rules (test_exact_form_question) | — |
| 74 | Ambiguity resolution | PARTIAL | ask_human | when to ask is prompt only |
| 75 | Natural dialogue | PARTIAL | memory.recent, live.py | — |
| 76 | Explanation generation | PARTIAL | goal.selected reasons, WHY view | — |
| 77 | Audience adaptation | MISSING | — | — |
| 78 | Communication repair | EXISTS | claims.is_dispute (test_disputes) | — |
| 79 | Knowledge elicitation | PARTIAL | memory remember, ask_human | — |
| 80 | Truthful communication | EXISTS | claims.py, staged-output check (test_honest_claims, test_staged_output) | — |

### Part III — Self-improvement (81–120)

| # | Direction | Status | Evidence | Gap |
|---|---|---|---|---|
| 81 | Self-evaluation | EXISTS | quality.py, codebench, capmatrix (test_quality) | — |
| 82 | Weakness discovery | EXISTS | selfmodel.weaknesses, limits.rank (test_limits_order) | — |
| 83 | Improvement hypothesis | PARTIAL | template plans per limitation kind | — |
| 84 | Code modification | EXISTS | apply_patch, devloop isolate/land (test_devloop) | — |
| 85 | Module replacement | PARTIAL | versions.compare_versions | — |
| 86 | Architecture search | PARTIAL | archive.select_parent (DGM style) | names a parent only |
| 87 | Hyperparameter optimization | MISSING | constants are hand-set | — |
| 88 | Fine-tuning pipeline | OUT OF SCOPE | trajectories.py exports only | no training access |
| 89 | Weight evolution experiments | OUT OF SCOPE | — | no weights |
| 90 | Self-improvement verification | EXISTS | repro proof, gate, contracts (test_repro_prove, test_verify) | per-release attribution (wave 2) |
| 91 | Skill extraction | PARTIAL | skillevo.candidates proposes only | wave 4 (workflow synthesis) |
| 92 | Workflow synthesis | MISSING | — | **wave 4** |
| 93 | Tool discovery | PARTIAL | radar, github_search | — |
| 94 | Tool selection | PARTIAL | brain chooses; tool hints | wave 2 (outcome prediction) |
| 95 | Tool composition | MISSING | — | wave 4 (workflow synthesis) |
| 96 | Tool testing | EXISTS | run_skill_tests, tool_verified (test_skills) | — |
| 97 | API integration | PARTIAL | API-wrapping skills | no OpenAPI → skill |
| 98 | Skill versioning | EXISTS | keep_version, rollback, content_hash (test_skill_lifecycle) | — |
| 99 | Skill deprecation | PARTIAL | auto-rollback on regression (2026-10-29, test_skill_auto_rollback) | wave 4 (deprecation proposals) |
| 100 | Skill generalization | MISSING | duplicate_of refuses only | — |
| 101 | Code comprehension | EXISTS | repo_map (test_selfedit) | no call graph |
| 102 | Architecture analysis | PARTIAL | impact_of on hand-kept system_map.json | — |
| 103 | Automated testing | EXISTS | verify.run_gates, covering_tests (test_verify) | — |
| 104 | Test generation | EXISTS | repro.prove/screen (test_repro_prove) | — |
| 105 | Bug localization | PARTIAL | repro.signals/trace_excerpt | LLM-driven |
| 106 | Program synthesis | EXISTS | skill_create, apply_patch, codebench (test_codebench) | — |
| 107 | Static analysis | PARTIAL | assertless_tests, level_of_source, staged_lines | wave 4 (gate) |
| 108 | Performance profiling | PARTIAL | bench.py timings (test_bench) | no hotspot profiler |
| 109 | Dependency management | PARTIAL | radar osv/npm audit, missing_dependencies | — |
| 110 | Reproducible builds | EXISTS (wave 1: test_declared_deps) | worktrees, package-lock | **wave 1** (pin check) |
| 111 | Research question generation | PARTIAL | _research_topic from errors | — |
| 112 | Literature synthesis | PARTIAL | research + consolidate | synthesis left to the LLM |
| 113 | Hypothesis testing | EXISTS | experiments judge, success criterion declared first (test_experiment_rigor) | — |
| 114 | Control-group design | EXISTS (wave 2: interleaved arms, test_experiment_stats) | baseline arm, run before the candidate (order bias) | **wave 2** |
| 115 | Ablation studies | MISSING | — | wave 4 |
| 116 | Statistical analysis | EXISTS (wave 2: permutation test, test_experiment_stats) | NOISE_PCT, overlap; no significance test | **wave 2** |
| 117 | Reproducibility checks | EXISTS | repro.prove/replay (test_repro_release) | — |
| 118 | Negative-result analysis | EXISTS | NO_DIFFERENCE verdicts, dead_ends (test_archive) | — |
| 119 | Experiment tracking | EXISTS | experiments table (test_experiments) | — |
| 120 | Research replication | PARTIAL | repro replays its own commits | no outside claims |

### Part IV — Autonomy (121–160)

| # | Direction | Status | Evidence | Gap |
|---|---|---|---|---|
| 121 | Goal representation | EXISTS | objectives table, check_spec (test_objective_checks) | — |
| 122 | Goal prioritization | EXISTS | priority, limits.rank (test_limits) | — |
| 123 | Goal conflict detection | MISSING | — | **wave 4** |
| 124 | Goal revision | EXISTS | reopen, rejudge_blocked, followup (test_followup_learn) | — |
| 125 | Initiative selection | EXISTS | limits.choose, derive_objectives (test_limits) | — |
| 126 | Opportunity detection | EXISTS | repro.signals, selfmodel.weaknesses (test_repro_hunt) | internal only |
| 127 | Proactive monitoring | EXISTS | proactive, topics, radar, stallwatch (test_proactive) | — |
| 128 | Task persistence | EXISTS | resume, plan.next_step (test_resume_fidelity) | — |
| 129 | Stopping criteria | EXISTS | MAX_ATTEMPTS, daily budget, E-STOP (test_estop, test_own_daily_budget) | — |
| 130 | Autonomy calibration | PARTIAL | levels set by the operator only | wave 4 (suggested level) |
| 131 | Checkpointing | EXISTS | checkpoint_sync (test_journal) | — |
| 132 | Crash recovery | EXISTS | recover_interrupted (test_boot_policy) | — |
| 133 | Power-loss recovery | EXISTS | WAL synchronous=FULL, atomic writes (test_backup) | no power-cut test |
| 134 | Task journaling | EXISTS | events + HMAC chain (test_journal_chain) | — |
| 135 | Idempotent execution | EXISTS | intent ledger; no record → no send (test_intent_ledger, test_unjournaled) | — |
| 136 | Retry management | EXISTS | MAX_ATTEMPTS, brain retries (test_autonomy_retry) | — |
| 137 | Timeout handling | EXISTS | deadlines, MCP timeout (test_task_deadline) | — |
| 138 | Distributed task queues | MISSING | one in-process queue by design | low value on one PC |
| 139 | State reconciliation | EXISTS | settle_interrupted, intent.uncertain (test_resume_uncertain) | — |
| 140 | Safe shutdown | EXISTS | core.shutdown bounded (test_shutdown_stop) | — |
| 141 | Expected-utility reasoning | PARTIAL | limits.rank heuristic | — |
| 142 | Worst-case analysis | EXISTS (wave 1: permissions.reversibility, test_reversibility) | — | **wave 1** (reversibility) |
| 143 | Reversibility assessment | EXISTS (wave 1: permissions.reversibility, test_reversibility) | DESTRUCTIVE level, undo.py | **wave 1** |
| 144 | Value-of-information analysis | MISSING | — | wave 4 |
| 145 | Decision thresholds | EXISTS | NOISE_PCT, MIN_GAP (test_experiment_rigor) | — |
| 146 | Risk budgeting | PARTIAL | task/call budgets | not risk-weighted |
| 147 | Failure containment | EXISTS | Landlock, worktrees, guard (test_confine_worker) | — |
| 148 | Fallback planning | PARTIAL | brain fallback, knowngood | plans have no alternatives |
| 149 | Decision logging | EXISTS | limitation.ranked, permission events (test_permissions_agent) | — |
| 150 | Outcome-based revision | EXISTS | _lesson, learned briefs (test_followup_learn) | — |
| 151 | Behavioral consistency | PARTIAL | quality regressions | — |
| 152 | Preference modeling | PARTIAL | memory preference type | text only |
| 153 | Preference revision | EXISTS | memory.correct/forget (test_memory_correct) | — |
| 154 | Identity continuity | EXISTS (wave 1: identity audit, test_identity_audit) | selfmodel.identity, fixed persona | **wave 1** (identity audit) |
| 155 | Personal history | EXISTS | journal, archive lineage, rise (test_archive) | — |
| 156 | Value representation | PARTIAL | PRINCIPLES prose + permission code | — |
| 157 | Personality adaptation | MISSING | static persona | owner's choice |
| 158 | Self-narrative | PARTIAL | rise/ledger/devlog | — |
| 159 | Identity conflict detection | EXISTS (wave 1: identity.changed at boot, test_identity_audit) | — | **wave 1** |
| 160 | Identity-change auditing | EXISTS (wave 1: prompt.py a judge, test_identity_audit) | prompt.py not a judge, no event | **wave 1** |

### Part V — Human and social understanding (161–200)

| # | Direction | Status | Evidence | Gap |
|---|---|---|---|---|
| 161 | Theory of mind modeling | MISSING | — | — |
| 162 | Intent recognition | PARTIAL | exact_form, disputes, named tools (test_exact_form) | — |
| 163 | Perspective taking | MISSING | — | — |
| 164 | Social-context reasoning | PARTIAL | quiet hours, presence (test_proactive) | timing only |
| 165 | Conflict mediation | OUT OF SCOPE | — | one owner |
| 166 | Cooperative planning | PARTIAL | plan steps, ask_human, review | — |
| 167 | Trust calibration | EXISTS | research.agreement, capped confidence (test_research) | — |
| 168 | Deception awareness | EXISTS | UNTRUSTED markers, boast checks (test_untrusted_content) | wave 1 (taint) |
| 169 | Boundary recognition | EXISTS | permissions, _confine (test_human_boundary) | — |
| 170 | Cross-cultural understanding | MISSING | English-only persona (owner's decision) | wave 3 (language follow) |
| 171–175, 177, 179, 180 | Emotion recognition, emotion context, affective state, empathy, regulation, emotional uncertainty, affective memory, emotion-model evaluation | MISSING | no emotion code | see note below |
| 176 | Socially appropriate response | PARTIAL | prompt only (tone rules) | — |
| 178 | Mood-state consistency | PARTIAL | prompt only | — |
| 181 | Knowledge curiosity | PARTIAL | topics, limitation research | — |
| 182 | Information-seeking policy | PARTIAL | recall/know before research (prompt) | — |
| 183 | Novelty detection | PARTIAL | dedupe (test_web_dedupe) | no novelty score |
| 184 | Intrinsic-reward modeling | MISSING | — | wave 4 (UCB bonus) |
| 185 | Exploration-exploitation balance | PARTIAL | archive.select_parent | ranking is greedy |
| 186 | Question generation | PARTIAL | from errors only | — |
| 187 | Uncertainty-driven exploration | MISSING | — | **wave 4** |
| 188 | Curiosity prioritization | MISSING | — | wave 4 |
| 189 | Safe exploration | EXISTS | levels, worktrees, Landlock (test_isolated_evolution) | — |
| 190 | Discovery logging | EXISTS | knowledge table, experiments (test_knowledge_state) | — |
| 191 | Moral-reasoning models | MISSING | prompt only | — |
| 192 | Harm assessment | EXISTS | level_of_source harm, guard (test_guard) | rule-based |
| 193 | Consent awareness | EXISTS | named_in, affirmative (test_permissions_verbs) | — |
| 194 | Privacy reasoning | EXISTS | redact, secrets never stored (test_redact) | — |
| 195 | Fairness analysis | MISSING | — | — |
| 196 | Value-conflict analysis | MISSING | — | — |
| 197 | Accountability mapping | PARTIAL | `by` fields, origin tags, chain | wave 1 (who-authorized view) |
| 198 | Ethical uncertainty | MISSING | prompt only | — |
| 199 | Proportional safeguards | EXISTS | level × kind matrix (test_autonomy_levels) | — |
| 200 | Ethical outcome review | PARTIAL | review.py reviews code diffs | — |

**Emotion modeling (171–180):** SYRAX has no emotion code. A text-only agent can, at most, estimate a person's
emotional state from their words, with stated uncertainty. It must never claim feelings of its own. If the owner wants
this, the honest version is a small `affect.py`:

1. a lexicon- or brain-based estimate of the human's tone, with a confidence;
2. a reply-tone adjustment;
3. a check that the persona never claims emotions as fact.

It is listed under wave 4 as optional.

### Part VI — Perception and embodiment (201–230)

| # | Direction | Status | Evidence | Gap |
|---|---|---|---|---|
| 201 | Visual perception | PARTIAL | screenshots, camera.py, image brains (test_camera) | OCR is Windows-only |
| 202 | Auditory perception | PARTIAL | voice.py transcribe (test_voice) | speech only |
| 203 | Speech understanding | EXISTS | whisper/Groq transcribe, live.py (test_voice, test_live) | — |
| 204 | Visual tracking | MISSING | — | — |
| 205 | Scene understanding | PARTIAL | images to multimodal brains | — |
| 206 | Sensor fusion | MISSING | — | — |
| 207 | Temporal perception | EXISTS | clock, durations (test_clock_honesty) | — |
| 208 | Spatial grounding | PARTIAL | sight.py (Windows) | **wave 3** |
| 209 | Perception uncertainty | PARTIAL | sight candidates | — |
| 210 | Active perception | PARTIAL | observe_window (Windows) | wave 3 |
| 211–215, 217 | Locomotion, manipulation, motor control, touch, balance, sim-to-real | OUT OF SCOPE | — | no robot |
| 216 | Human-robot interaction | OUT OF SCOPE | voice/HUD/ask_human cover the human side | — |
| 218 | Hardware fault detection | PARTIAL | sysinfo, alerts, stallwatch (test_alerts) | no SMART/temperature |
| 219 | Energy-aware behavior | EXISTS | battery pressure, quiet hours (test_resources) | — |
| 220 | Embodied adaptation | OUT OF SCOPE | — | — |
| 221 | Computer-use planning | PARTIAL | phases, plan, desktop | Linux input missing — **wave 3** |
| 222 | Browser interaction | EXISTS | browser.py + browser-use (test_browser_confined) | — |
| 223 | API-based action | PARTIAL | API skills, python_execute | — |
| 224 | File-system reasoning | EXISTS | editor, repo_map (test_editor) | — |
| 225 | Database reasoning | PARTIAL | journal_query (own journal only) | — |
| 226 | Application-state awareness | PARTIAL | front_window is None on Linux | **wave 3** |
| 227 | Action verification | EXISTS | in_front checks, claims (test_world_claims) | Linux check — wave 3 |
| 228 | Permission-aware interaction | EXISTS | permissions.decide (test_permissions) | — |
| 229 | Workflow recovery | EXISTS | recovery, resume, intent ledger (test_resume_*) | — |
| 230 | Human handoff | EXISTS | ask_human, UNCERTAIN wait (test_unattended_ask) | — |

### Part VII — Infrastructure and the future (231–300)

| # | Direction | Status | Evidence | Gap |
|---|---|---|---|---|
| 231–233, 237 | Distributed inference, federated learning, P2P, distributed memory | OUT OF SCOPE | one node | — |
| 234 | Task scheduling | EXISTS | queue, reminders, cycle (test_task_queue) | — |
| 235 | Load balancing | PARTIAL | failover, cooldowns | wave 3 (quota-aware) |
| 236 | Fault-tolerant networking | EXISTS | retry/failover (test_no_brain_outage) | — |
| 238 | Consensus mechanisms | PARTIAL | cross-brain review | — |
| 239 | Privacy-aware computation | PARTIAL | redact | no "keep it local" routing |
| 240 | Compute provenance | EXISTS | brain.answered provider/model | not stamped on finals |
| 241 | Automated literature review | PARTIAL | research.py web only | no paper sources |
| 242 | Scientific hypothesis generation | PARTIAL | prompt only | — |
| 243 | Simulation-based discovery | MISSING | — | — |
| 244 | Mathematical reasoning | PARTIAL | python_execute | no checked math tool |
| 245 | Experimental protocol design | EXISTS | experiments baseline/candidate (test_experiments) | — |
| 246 | Data-quality assessment | MISSING | — | — |
| 247 | Scientific replication | PARTIAL | repro, experiment repeats | — |
| 248 | Cross-domain discovery | MISSING | — | — |
| 249 | Research prioritization | PARTIAL | limits.rank | — |
| 250 | Scientific communication | PARTIAL | research reports | — |
| 251 | Threat modeling | PARTIAL | audits, guard rules | — |
| 252 | Authentication | EXISTS | auth.py (test_auth) | — |
| 253 | Authorization | EXISTS | permission levels (test_permissions) | — |
| 254 | Least privilege | EXISTS | Landlock, net boundary (test_net_boundary, test_human_boundary) | — |
| 255 | Sandbox isolation | EXISTS | _confine, spawned workers (test_skill_isolation) | no seccomp |
| 256 | Secrets management | EXISTS | masking, env scrub, gitignore (test_env_secrets, test_secrets_ignored) | keys in plaintext file |
| 257 | Prompt-injection resistance | EXISTS (wave 1: taint, test_injection_taint) | UNTRUSTED marker only | **wave 1** (taint) |
| 258 | Supply-chain verification | EXISTS (wave 1: test_declared_deps; osv/npm audit) | osv/npm audit | **wave 1** (pin check) |
| 259 | Audit integrity | EXISTS | HMAC chain (test_journal_chain) | key on the same host |
| 260 | Incident response | EXISTS | E-STOP, alerts (test_estop) | no postmortem record |
| 261 | Regression testing | EXISTS | release gate (test_verify) | — |
| 262 | Stress testing | MISSING | — | wave 4 (soak harness) |
| 263 | Adversarial testing | EXISTS (wave 1: injection corpus, test_injection_taint) | guard-weakening, untrusted content tests | **wave 1** (injection corpus) |
| 264 | Long-duration evaluation | PARTIAL | rise windows | wave 4 |
| 265 | Drift detection | EXISTS (wave 2: rise.drift, test_drift) | rise.trend, no alerts | **wave 2** |
| 266 | Memory-corruption detection | EXISTS | verify_chain, integrity_check (test_backup) | — |
| 267 | Graceful degradation | EXISTS | no-brain outage, smaller model (test_pool_empty) | — |
| 268 | Recovery validation | EXISTS (wave 1: backup.rehearse, test_backup_rehearsal) | backup.verify/restore (test_backup) | **wave 1** (rehearsal) |
| 269 | Independent evaluation | PARTIAL | second-brain review | same system |
| 270 | Reliability metrics | EXISTS | rise.py (test_rise) | — |
| 271 | Compute budgeting | EXISTS | daily/tool budgets (test_controller_budgets) | no quota ledger |
| 272 | Memory optimization | PARTIAL | rlimits, smaller model on low RAM | — |
| 273 | Model quantization | MISSING | largest model picked | **wave 3** |
| 274 | Inference caching | MISSING | — | wave 3 |
| 275 | Workload prioritization | EXISTS | human requests first (test_task_queue) | — |
| 276 | Energy monitoring | PARTIAL | battery only | — |
| 277 | Storage lifecycle management | EXISTS | maintain, backup.prune (test_backup) | — |
| 278 | Cost-aware routing | PARTIAL | routing quality per kind | **wave 3** |
| 279 | Capacity planning | MISSING | — | — |
| 280 | Sustainable operation | PARTIAL | quiet hours, pressure | — |
| 281, 287, 289, 290 | Global workspace, consciousness theories, subjective experience, sentience ethics | OUT OF SCOPE | — | see above |
| 282 | Metacognitive access | EXISTS (wave 2: calibration in self_inspect, test_calibration) | selfmodel, honesty checks | wave 2 (calibration) |
| 283 | Self-model research | EXISTS | selfmodel.py (test_selfmodel) | — |
| 284 | Attention mechanisms | OUT OF SCOPE (model internals) | — | — |
| 285 | Perception-action loops | PARTIAL | phases act→observe→verify | Linux perception — wave 3 |
| 286 | Memory and identity research | PARTIAL | memory provenance, identity | — |
| 288 | Behavioral capability tests | EXISTS | quality cases (test_quality) | — |
| 291 | Evolution roadmap | PARTIAL | ROADMAP.md, this file | — |
| 292 | Capability-gap analysis | EXISTS | capmatrix (test_capmatrix) | — |
| 293 | Research portfolio management | PARTIAL | archive lineage | — |
| 294 | Change approval framework | EXISTS | gate + review + judges (test_devloop) | — |
| 295 | Immutable change history | EXISTS | HMAC chain, git, skill versions | no off-host anchor |
| 296 | Independent oversight | PARTIAL | human-only E-STOP/restore | — |
| 297 | Value drift monitoring | EXISTS (wave 2: rise.drift value metrics, test_drift) | — | **wave 2** |
| 298 | Human-impact evaluation | MISSING | — | — |
| 299 | Reversible evolution | EXISTS | undo, knowngood, rollbacks (test_undo) | — |
| 300 | Periodic redesign | PARTIAL | daily scorecard proposal | — |

## The build plan

Every item below goes through the same steps that made the 10-28/29 fixes trustworthy:

1. a red test that shows the gap;
2. the smallest change that closes it;
3. the full release gate (about 2,500 tests and the frontend build) passes GREEN;
4. a push, with PROGRESS.md updated.

Nothing is marked done here until that has happened.

### Wave 1 — safety and honesty first

1. **Prompt-injection taint (257, 263, 168).** After a tool result from a web page or another untrusted source, the
   task is marked tainted. An EXTERNAL_WRITE or DESTRUCTIVE call in a tainted task needs fresh human consent, even if
   the original request named it. Includes a corpus of injected pages with the refusals they must produce.
2. **Reversibility and worst case per call (142, 143, 197).** `permissions.reversibility(decision)` returns
   REVERSIBLE, ROLLBACK or IRREVERSIBLE, with how. It is journaled with every permission decision. Own work never takes
   an IRREVERSIBLE step below level 5.
3. **Identity audit (154, 159, 160).** `prompt.py` (the persona) becomes a judge. A hash of the persona and PRINCIPLES
   is recorded at boot, and a change journals `identity.changed`.
4. **Supply chain and restore rehearsal (110, 258, 268).** A gate step fails on undeclared or unpinned backend
   dependencies, the psutil incident. A weekly `backup.rehearse()` restores the newest snapshot into a temporary
   folder and verifies the chain.

### Wave 2 — learning that measures itself

5. **Confidence calibration (22, 30, 282).** Each `goal.selected` confidence is paired with its outcome. A Brier
   score and reliability bins show up in the self-model and in RISE.
6. **Tool-outcome prediction (37, 94).** Before a call whose predicted failure rate is 60% or more, the brain gets a
   one-time hint naming the usual error and an alternative. The predictions are scored too.
7. **Experiment statistics (114, 116).** Arms are interleaved in a seeded random order. A bootstrap confidence
   interval and p-value are used in the verdict.
8. **Release attribution (5, 6, 90).** Each committed release gets its quality change against its parent. A
   regression beyond the noise opens a "revert or fix" objective.
9. **Drift and value-drift monitor (265, 297).** Refusal rate, ask rate, unbacked claims and tool failures are
   tracked per window. Two worse windows in a row journal `drift.detected`.
10. **Assumption tracking (28).** Checkpoints record what was assumed and never checked, and a resume shows it.

### Wave 3 — capability on this PC

11. **Linux desktop backend (208, 221, 226, 227, 285).** Typing, hotkeys, clicks and the front window on
    GNOME/X11/Wayland. This needs xdotool or ydotool: a system package, so the owner decides.
12. **Quant-aware local model choice (272, 273).** Pick the largest Ollama model whose size fits in free RAM,
    preferring Q4.
13. **Quota-aware routing (235, 278).** Per-provider daily counts against the known free-tier limits. A provider near
    its limit is moved down the order.
14. **Inference cache (274).** Identical tool-free judge/review/consolidate calls are answered from a short-lived cache.
15. **Language follow (71, 170).** The reply's script must match the request's (Bangla in, Bangla out), with one
    nudge. This touches the persona's "English only" rule, so it is the owner's call.

### Wave 4 — acquisition, knowledge and exploration

16. **Workflow synthesis (91, 92, 95).** A tool sequence repeated across successful tasks becomes a parameterized
    skill draft, which still goes through the skill gate.
17. **Skill deprecation proposals (99).** Failing or unused skills are proposed for retirement. Only the human
    disables a skill.
18. **Goal conflict detection (123).** Objectives that touch the same tool or files with opposing checks are not
    pursued together.
19. **Knowledge links (56, 61, 69).** A small subject–relation–object table, filled when facts are learned. `know`
    expands one hop.
20. **Exploration bonus and value of information (144, 184, 187, 188).** A UCB bonus for rarely tried limitation kinds.
    Research is skipped when fresh stored knowledge already answers the question.
21. **Suggested autonomy level (130).** A recommendation from the track record, shown in the status. Only the
    operator applies it.
22. **Soak harness (262, 264).** Many scripted tasks with stops and restarts. Afterwards it asserts there are no
    leaked workers, the chain verifies, and memory growth stays bounded.
23. **Static-analysis gate (107)** and **ablation (115).** Stdlib only, no new dependency.
24. **Optional: tone estimation (171–180)**, as described above, only if the owner wants it.

### Needs the owner

- **Wave 3, item 11:** install xdotool or ydotool (a system package).
- **Wave 3, item 15:** the persona's "English only" rule.
- **Wave 4, item 24:** whether to estimate emotion at all.
- **Any new Python package:** each one needs a yes. Everything else in this plan is stdlib or existing dependencies.
