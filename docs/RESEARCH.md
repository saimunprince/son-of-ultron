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

## Tools

- `research {question, max_sources}` — the flow above; emits `research.started` / `research.completed`.
- `know {query}` — keyword-ranked search over stored knowledge; bumps `uses` / `last_used`.
- `learn {claim, sources, confidence?, tags?}` — stores a `conclusion` that must cite
  knowledge_ids or URLs; unknown ids and uncited claims are refused; confidence is
  capped by the cited evidence.

The tool guide tells the model: check `know`, then `research`; never present an
unresearched guess as fact.

## Closing the loop with objectives

A FAILED task whose error is researchable (a missing module, an exception with a
message, or at least two meaningful words; never an abort or a brain outage)
becomes a `research-failure:<task_id>` objective with check
`knowledge_stored {topic}`: it is DONE only when knowledge matching the topic
was stored after the objective was created. Words in the final reply do not count.

## Access

- WebSocket `knowledge {query?, limit?}` → `knowledge_list` (recent, or ranked by query).
- Self-model `behavior.knowledge` (count, recent) and summary `knowledge_count`.

## Limits (honest list)

- Extraction is keyword overlap, not semantic; agreement is term overlap, not
  claim-level agreement. Contradicting sources are shown, not detected.
- Only web and conclusion kinds are produced automatically; `local` and
  `experiment` kinds exist in the policy but nothing stores them yet.
- Search depends on DuckDuckGo being reachable; there is no cache and no rate limiting.
- No knowledge expiry or supersession.
