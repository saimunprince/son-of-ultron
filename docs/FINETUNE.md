# Learning data for SYRAX's own brain

Phase 8 of the self-improvement plan (2026-10-14). SYRAX keeps every task it
runs in its journal: the request, each thought with the tool calls it chose,
what the tools returned, the final answer, and the verdicts the judges gave
(a quality case passed or failed, an answer sent back for a false claim or a
missing source). `backend/syrax/trajectories.py` turns that into training
data.

## Export

```powershell
cd backend
.\.venv\Scripts\python.exe -m syrax.trajectories --since 30
# {"out": ".../backend/workspace/exports/trajectories-20261014.jsonl", "exported": 212, "pass": 180, "fail": 12, ...}
```

The file lands in `backend/workspace/exports/` (gitignored). Nothing leaves
the machine; the export is never committed. Run it against the live journal
while SYRAX runs (it opens the journal read-only, `recover=False`).

First live export, 2026-10-14 (7 days of journal): 274 trajectories, 104
graded pass, 18 fail, 4 sent back, 148 ungraded; 17 skipped as secret-looking
and 119 repeats dropped.

## Format

One JSON object per line:

| field | meaning |
|---|---|
| `task_id`, `kind`, `status`, `created` | the task (`conversation`, `eval` = a quality case, `autonomous` = SYRAX's own work) |
| `grade` | `pass` / `fail` (a quality case the suite judged), `sent_back` (a false claim or an uncited answer the console rejected), `ungraded` |
| `tools` | the tools that returned, in order |
| `messages` | chat with tools: `user` (the request, or an answer to a question), `assistant` (`content`, optional `tool_calls` = `[{id, name, arguments}]`), `tool` (`tool_call_id`, `name`, `content`, `ok`, `refused`), the final `assistant` |

`terminate` is dropped (it is the loop's end, not an action). Tool outputs
are the previews the journal kept (`RESULT_PREVIEW_CHARS`), not full stdout.

## What is kept out

- A task whose text matches the secret pattern (keys, passwords, tokens) is
  skipped whole; the count is reported as `skipped_secret`.
- One prompt is kept at most three times (`MAX_PER_GOAL`): the quality suite
  repeats its cases every run and would otherwise dominate.
- Tasks without a final answer (cancelled, interrupted) are not trajectories.

## How to use it

The intent (ROADMAP, Phase 7: learn → experiment → fine-tune / distill) is a
small local model that handles SYRAX's everyday tool use so the free-tier
brains are spent on hard work:

1. Keep `grade == "pass"` and the `ungraded` conversations a human checked;
   use `fail` and `sent_back` as negatives (DPO pairs: the rejected answer
   against the rewritten one in the same task).
2. Train a LoRA on an instruction model with tool-call support (the JSONL is
   the OpenAI-style chat-with-tools shape most trainers accept directly).
3. Add the model to SYRAX as an Ollama brain (BRAIN panel) and let
   `compare_brains` and the quality suite judge it against the current one;
   the archive (`docs/ARCHIVE.md`) scores what lands.

Decisions only the owner takes: which model, where it trains (this machine
or a paid one), and whether any of this data ever leaves the machine.
