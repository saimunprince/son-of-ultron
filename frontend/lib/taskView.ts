// Decisions the live console (components/Syrax.tsx) makes about the running task, kept pure here so
// `node --experimental-strip-types --test lib/taskView.test.ts` covers them without a browser.
import type { JournalEvent } from "./syraxClient";

// Journal types after which a question no longer waits: the human answered (core.py answer -> "answer"), the agent
// moved on (a question that timed out returns into the ask_human tool's result, tools.py WebAskHuman.execute, and the
// next step thinks), or the task ended (task.completed / failed / cancelled / ...).
const SETTLES_ASK = new Set(["answer", "think", "final", "tool.started", "tool.completed", "tool.failed"]);

/** The question the running task still waits on, from its journal events (server.py boot sends them as
 *  `task_events` when a UI connects while a task runs). The hello snapshot carries no pending question, so
 *  without this a reload forgets it and the typed answer goes out as a new task. null when none waits. */
export function pendingAskFrom(events: readonly JournalEvent[] | null | undefined): string | null {
  let question: string | null = null;
  for (const ev of events ?? []) {
    if (!ev || typeof ev.type !== "string") continue;
    if (ev.type === "ask") question = typeof ev.payload?.question === "string" ? ev.payload.question : "";
    else if (SETTLES_ASK.has(ev.type) || ev.type.startsWith("task.")) question = null;
  }
  return question;
}
