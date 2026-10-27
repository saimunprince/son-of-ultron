# SYRAX Research Engine and Knowledge Store

Implemented in `backend/syrax/research.py` (engine + tools) and the `knowledge`
table in `backend/syrax/journal.py`. Tests: `backend/syrax/test_research.py`,
the research section of `test_bridge.py`, and the research-objective test in
`test_autonomy.py`.

## Flow

```
question
  → search: ddgs (DuckDuckGo API client), then DuckDuckGo lite HTML (no extra dependency)
  → fetch each page (requests + BeautifulSoup, upstream WebContentFetcher, 10 KB cap)
  → extract passages whose words overlap the question (420-char windows, top 2 per source)
  → agreement: sources sharing ≥3 key terms with another source count as agreeing
  → store one knowledge row per source with an excerpt: kind=web, URL, title, tags,
    question, task id, basis text, confidence from the agreement count
  → return sources + excerpts + knowledge_ids to the model
```

The engine never writes a claim it did not read: rows are verbatim excerpts.
When no engine returns anything, the report says `UNKNOWN` and nothing is stored.
A page that cannot be fetched falls back to the search snippet and its basis
says so.

## Confidence policy (`journal.confidence_for`)

| kind | confidence |
|---|---|
| web, 1 source | 0.40 |
| web, 2 agreeing sources | 0.60 |
| web, 3+ agreeing | 0.75 |
| local (source code, installed packages) | 0.90 |
| experiment (a tool result) | 0.95 |
| human | 1.00 |
| conclusion | ≤ max confidence of the sources it cites |

A caller may lower a confidence, never raise it above the policy.

Memory rows (`remember`, kind `human`) carry a type tag: fact / preference / rule are the
human's own words at 1.00, observation is SYRAX's inference at 0.50. Since 2026-10-25 the
tool grounds the text in what the human said this task (a normalized substring, or 60% of
its content words): text the model invented is stored as an observation with basis "SYRAX
inferred from the conversation", never as a fact, and the reply says so. An overwrite
journals `previous` (old text, type, confidence) in `knowledge.updated`, and the row takes
the new type and confidence (a human fact over an observation is a fact at 1.00). Since
2026-10-27 the old text is also kept as a row (see Knowledge state below).

## Knowledge state (audit 2026-10-27, item 4)

Every `knowledge` row carries its own state; before, DISPUTED was recomputed by `know`
from the last 3000 events and aged out, and an overwrite left 160 characters in an event.

| column | meaning |
|---|---|
| `status` | `ACTIVE` (believed), `DISPUTED` (another stored row contradicts it), `SUPERSEDED` (replaced; history) |
| `verified_at` | when the row was last checked against a source: set when a row with a source is stored, when `research` finds the same page excerpt again, and when `learn` confirms or settles it with independent evidence. NULL for the human's own word (no source to check) |
| `superseded_by` | the row that replaced a SUPERSEDED one |

Transitions (`journal.KNOWLEDGE_TRANSITIONS`, enforced in the journal, each journaled in
the same transaction): ACTIVE → DISPUTED | SUPERSEDED, DISPUTED → ACTIVE | SUPERSEDED;
SUPERSEDED is final, and a row only supersedes rows of its own kind.

- **Dispute.** A `learn` that contradicts stored conclusions (consolidate.py) marks the
  rows involved DISPUTED: `knowledge.disputed {knowledge_ids, disputed, why}`, written with
  the `knowledge.contradiction` that found it.
- **Settle.** A later `learn` settles a dispute when a row involved is already DISPUTED and
  the claim cites *independent* evidence (a stored source row, not a conclusion, whose text
  fully supports the claim, that none of the involved rows is or cites) at least as strong
  as every row it contradicts. The row the claim confirms (or the new row) becomes ACTIVE and
  verified, the rows it contradicts SUPERSEDED: `knowledge.superseded {knowledge_ids,
  superseded_by, was, why, evidence}`. Citing the same rows again settles nothing, and a first
  contradiction is always disputed first, never settled on the spot.
- **Resolve.** A DISPUTED row confirmed by independent evidence with nothing stored left to
  contradict it is ACTIVE again (`knowledge.resolved`).
- **Correction.** `memory correct` and a `remember` that overwrites a fact keep the row's id
  (the memory panel's references stay valid) and copy the old version into a new row,
  SUPERSEDED, `superseded_by` the fact; `knowledge.updated` names it as `previous_id`.
  Forgetting a fact deletes its earlier versions too (`knowledge.forgotten.versions`).

Readers: `know` (`knowledge_search`), `knowledge_recent`, `human_facts` (memory facts,
`recall`, the prompt) skip SUPERSEDED rows; `know`, `recall` and the prompt mark a DISPUTED row
"(disputed)" so the brain does not state it as fact; `learn` refuses a SUPERSEDED row as a
source; consolidate compares a claim with no SUPERSEDED row. `knowledge(id)` and
`knowledge_of_kind` return every row with its status. The memory export carries `status` on
every fact and knowledge row (plus `verified_at`, `superseded_by` on knowledge) and the
replaced versions in `superseded_facts`.

Migration: the columns are added in place (`_ADDED_COLUMNS`, in one transaction with the
backfill); ids and rows are unchanged. Old rows are ACTIVE: the three contradiction events in
the live journal name 78.4 °C vs 78.37 °C, which `consolidate.agree` has treated as the same
figure since 2026-10-26, so replaying them would dispute correct rows. Old rows with a source
(every kind but `human`) get `verified_at = created`. A read-only handle on a journal whose
owner still runs the old schema reads it unmigrated, every row ACTIVE.

## Tools

- `research {question, max_sources}` — the flow above; emits `research.started` / `research.completed`.
- `know {query}` — keyword-ranked search over stored knowledge (not SUPERSEDED rows); bumps
  `uses` / `last_used`; a DISPUTED row is marked "(disputed)" with the ids it contradicts.
- `learn {claim, sources, confidence?, tags?}` — stores a `conclusion` that must cite
  knowledge_ids or URLs; unknown ids and uncited claims are refused; confidence is
  capped by the cited evidence. A cited row must also support the claim (memory truth,
  2026-10-25): share three content words (lower-cased, no stopwords, 4+ letters) or a
  number/year with it. A row that shares nothing is refused ("knowledge_id N does not
  support the claim: cite the rows whose text does") and nothing is stored; a row that
  shares only a word or two is weak support: stored at half the cap, labelled in the
  basis and in the reply.

The tool guide tells the model: check `know`, then `research`; never present an
unresearched guess as fact.

## Closing the loop with objectives

A FAILED task whose error is researchable (a missing module, an exception with a
message, or at least two meaningful words; never an abort or a brain outage)
becomes a `research-failure:<task_id>` objective with check
`knowledge_stored {topic}`: it is DONE only when knowledge matching the topic
was stored after the objective was created. Words in the final reply do not count.

Human objectives (`objective_add {goal, check?}`) can carry the same kind of
machine check instead of the default `task_success` (which only asks whether
the task ended SUCCESS, so an honest refusal or a report with no change
closes it): `change_released` (a `commit.created` by this objective's own
task), `file_present {path}` / `file_absent {path}` (a real look at the tree,
inside the repository only; a present file counts only if written after the
objective was set), `quality_case_passes {case}`, `tool_verified {tool}`,
`skill_verified {name}`, `knowledge_stored {topic}`. A check with a missing
field or a path outside the repository is refused with a notice.

## Access

- WebSocket `knowledge {query?, limit?}` → `knowledge_list` (recent, or ranked by query).
- Self-model `behavior.knowledge` (count, recent) and summary `knowledge_count`.

## Limits (honest list)

- Extraction is keyword overlap, not semantic; agreement is term overlap, not
  claim-level agreement. Contradicting sources are shown, not detected.
- Only web and conclusion kinds are produced automatically; `local` and
  `experiment` kinds exist in the policy but nothing stores them yet.
- Search depends on DuckDuckGo being reachable; there is no cache and no rate limiting.
- No knowledge expiry. Supersession is by settled disputes and corrections only: a web row
  is never superseded, and a conclusion that is merely old is not re-checked.
- The autonomy cycle still opens settle-objectives from `knowledge.contradiction` events (the
  last 2000), not from DISPUTED rows; a dispute older than that window keeps its status but gets
  no new objective.
