// Decisions the live console (components/Syrax.tsx) makes about the running task, kept pure here so
// `node --experimental-strip-types --test lib/taskView.test.ts` covers them without a browser.
import type { JournalEvent } from "./syraxClient";

// Journal types after which a question no longer waits: the human answered (core.py answer -> "answer"), the agent
// moved on (a question that timed out returns into the ask_human tool's result, tools.py WebAskHuman.execute, and the
// next step thinks), or the task ended (task.completed / failed / cancelled / ...).
const SETTLES_ASK = new Set(["answer", "think", "final", "tool.started", "tool.completed", "tool.failed"]);

/** When the task ends (state idle), a tool row still "running" never got its result: a stop or a crash re-raises
 *  in agent.py before tool_result is sent. Those rows are marked "stopped" so none says RUN forever. Returns the
 *  same array when nothing changed (no re-render). */
export function stopRunningTools<T extends { kind: string; status?: string }>(entries: T[]): T[] {
  if (!entries.some((x) => x.kind === "tool" && x.status === "running")) return entries;
  return entries.map((x) => (x.kind === "tool" && x.status === "running" ? { ...x, status: "stopped" } : x));
}

/** Whether an event means the question SYRAX asked no longer waits, so the next thing typed is a new request:
 *  - `state` idle (the task ended) or thinking (agent.py: the next step starts, so the question was answered or
 *    timed out; tools.py returns "did not answer in time" into the tool's result and the agent goes on);
 *  - `user` with a task_id: an answer, from this UI or another, journaled as "answer" and sent as `user`
 *    (journal.py _WIRE). A new request's echo (server.py: {type: "user", text, voice}) has no task_id.
 *  `acting` does not settle it: the agent reports acting on a tool before that tool asks (agent.py tool_start ->
 *  state acting -> the ask or the permission question), and a reconnect replays that state while SYRAX waits. */
export function settlesPendingAsk(type: string, detail: { state?: string; task_id?: string | null }): boolean {
  if (type === "state") return detail.state === "idle" || detail.state === "thinking";
  if (type === "user") return !!detail.task_id;
  return false;
}

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
