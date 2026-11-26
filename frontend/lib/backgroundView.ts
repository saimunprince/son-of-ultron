/** The Background panel's view of the background lane (backend/syrax/background.py): pure helpers, tested alone. */

export type BackgroundState = "running" | "paused" | "done" | "cancelled" | "failed";

/** BgTask.summary() on the backend */
export interface BackgroundTask {
  id: string;
  instruction: string;
  state: BackgroundState;
  step: number;
  steps: number;
  minutes: number;
  elapsed_min: number;
  notes_waiting: number;
  finishing: boolean;
  folder: string;
  report: string | null;
  error: string | null;
  refused: number;
  started_at?: number;
  ended_at?: number | null;
}

/** A report the panel asked for: its text, or why there is none. */
export interface BackgroundReport {
  id: string;
  text?: string;
  error?: string;
}

export const ACTIVE_STATES: BackgroundState[] = ["running", "paused"];

export function isActive(t: Pick<BackgroundTask, "state">): boolean {
  return ACTIVE_STATES.includes(t.state);
}

export function stateLabel(t: Pick<BackgroundTask, "state" | "finishing">): string {
  if (t.state === "running" && t.finishing) return "WRITING UP";
  if (t.state === "paused") return "PAUSED · BRAINS OUT";
  return t.state.toUpperCase();
}

/** The row's status class, in the brain panel's terms: running reads as active, ended as ready, failed as hot. */
export function stateClass(state: BackgroundState): string {
  if (state === "running") return "status-ready active";
  if (state === "paused") return "status-cooldown";
  if (state === "failed") return "status-failed";
  if (state === "cancelled") return "status-off";
  return "status-ready";
}

/**
 * Seconds worked: the backend's elapsed_min as of when the list arrived, plus the time since for a running task
 * (a paused one does not count its pause, as on the backend; an ended one is fixed).
 */
export function elapsedSeconds(t: Pick<BackgroundTask, "state" | "elapsed_min">, receivedAt: number, now: number): number {
  const base = Math.max(0, t.elapsed_min * 60);
  return t.state === "running" ? base + Math.max(0, (now - receivedAt) / 1000) : base;
}

export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

/** "3 / 30 steps · 4:05 / 20 min" */
export function budgetLine(t: Pick<BackgroundTask, "step" | "steps" | "minutes">, seconds: number): string {
  return `${t.step} / ${t.steps} steps · ${formatElapsed(seconds)} / ${t.minutes} min`;
}

/** Running ones first, then the newest; the backend's own order (newest first) breaks ties. */
export function sortTasks(items: BackgroundTask[]): BackgroundTask[] {
  return items
    .map((t, i) => ({ t, i }))
    .sort((a, b) => Number(isActive(b.t)) - Number(isActive(a.t)) || (b.t.started_at ?? 0) - (a.t.started_at ?? 0) || a.i - b.i)
    .map(({ t }) => t);
}

export function activeCount(items: BackgroundTask[]): number {
  return items.filter(isActive).length;
}
