// Pure helpers for the brain chip (components/BrainChip.tsx).

/**
 * A model id as a person reads it: no vendor path, no dated snapshot, no
 * ":free" tag. "models/gemini-2.5-flash-preview-05-20" -> "gemini-2.5-flash",
 * "meta-llama/llama-3.3-70b-instruct:free" -> "llama-3.3-70b-instruct".
 */
export function shortModel(model: string | null | undefined, max = 24): string {
  if (!model) return "";
  let m = model.trim();
  m = m.slice(m.lastIndexOf("/") + 1);
  m = m.replace(/:[a-z0-9_.-]+$/i, "");
  m = m.replace(/-(\d{8}|\d{4}-\d{2}-\d{2}|latest)$/i, "");
  m = m.replace(/-preview(-\d{2}-\d{2})?$/i, "");
  return m.length > max ? `${m.slice(0, max - 1)}…` : m;
}

/** "840 ms", "2.4 s", "14 s"; "" when unknown. */
export function formatLatency(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 10_000) return `${(Math.floor(ms / 100) / 10).toFixed(1)} s`;
  return `${Math.round(ms / 1000)} s`;
}

export type LatencyTone = "fast" | "ok" | "slow" | "none";

/** The dot's tone: under 1.5 s is fast, over 6 s is slow. */
export function latencyTone(ms: number | null | undefined): LatencyTone {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "none";
  return ms < 1500 ? "fast" : ms <= 6000 ? "ok" : "slow";
}

/** "GEMINI FAILED → GROQ", or "GEMINI FAILED" while the next brain is unknown. */
export function failoverText(from: string | null | undefined, to?: string | null): string {
  // live 2026-11-04: a brain event without a provider reached here and `from.trim()` took the whole page down
  const a = (from ?? "").trim().toUpperCase() || "BRAIN";
  const b = to?.trim().toUpperCase();
  return b && b !== a ? `${a} FAILED → ${b}` : `${a} FAILED`;
}

/** Whether a failover warning is still fresh enough to show. */
export function failoverActive(failover: { at: number } | null | undefined, now: number, windowMs = 3000): boolean {
  return !!failover && now - failover.at >= 0 && now - failover.at < windowMs;
}

export interface LatencyTracker {
  /** A brain call starts now (state "thinking", a tool_result). Keeps the earliest open mark. */
  mark(at?: number): void;
  /** The brain answered: ms since the open mark, or null when nothing was marked. Closes the mark. */
  answered(at?: number): number | null;
  /** Forget an open mark (the task ended). */
  reset(): void;
}

/**
 * Measures brain latency on the client, since the "brain answered" event
 * carries no timing: mark() when a brain call starts, answered() when it ends.
 */
export function createLatencyTracker(now: () => number = Date.now): LatencyTracker {
  let since: number | null = null;
  return {
    mark(at = now()) {
      if (since === null) since = at;
    },
    answered(at = now()) {
      if (since === null) return null;
      const ms = Math.max(0, at - since);
      since = null;
      return ms;
    },
    reset() {
      since = null;
    },
  };
}
