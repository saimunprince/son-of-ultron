/**
 * Notification toasts (2026-11-03): the HUD's log lines that deserve a glance get a small card
 * in the bottom-right corner. Pure helpers only; the timer and hover pause live in components/Toasts.tsx.
 * No relative value imports: node --experimental-strip-types runs the tests on this file alone.
 */

export type ToastKind = "reminder" | "checkin" | "alert" | "done" | "news" | "camera" | "lesson" | "info" | "error";

export type Toast = { id: number; kind: ToastKind; title: string; text: string; ttlMs: number; createdAt: number };

export type ToastSpec = { kind: ToastKind; title: string; text: string };

export const TOAST_MAX = 3;
export const TOAST_TTL_MS = 6000;
export const TOAST_TTL_URGENT_MS = 9000;
/** a toast is a glance, not a page: the full line stays in the log */
export const TOAST_TEXT_MAX = 160;

/** errors and alerts stay up longer: they are the ones worth reading twice */
export function ttlFor(kind: ToastKind): number {
  return kind === "error" || kind === "alert" ? TOAST_TTL_URGENT_MS : TOAST_TTL_MS;
}

export function makeToast(id: number, spec: ToastSpec, now: number): Toast {
  return { id, kind: spec.kind, title: spec.title, text: spec.text, ttlMs: ttlFor(spec.kind), createdAt: now };
}

/** newest last (rendered nearest the screen edge); the same card again replaces the older copy; oldest drop past `max` */
export function addToast(list: readonly Toast[], toast: Toast, max: number = TOAST_MAX): Toast[] {
  const rest = list.filter((t) => !(t.id === toast.id || (t.kind === toast.kind && t.title === toast.title && t.text === toast.text)));
  const next = [...rest, toast];
  const keep = Math.max(0, Math.floor(max));
  return keep === 0 ? [] : next.slice(-keep);
}

export function dismissToast(list: readonly Toast[], id: number): Toast[] {
  return list.filter((t) => t.id !== id);
}

/** drops toasts whose time ran out (hover pauses are not known here: a safety net, not the main timer) */
export function expire(list: readonly Toast[], now: number): Toast[] {
  return list.filter((t) => t.createdAt + t.ttlMs > now);
}

function clip(text: string): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > TOAST_TEXT_MAX ? `${t.slice(0, TOAST_TEXT_MAX - 1).trimEnd()}…` : t;
}

/** "X · " prefix → the rest, or null (the line is trimmed, so "X ·" with nothing after counts too) */
function after(text: string, prefix: string): string | null {
  if (text.startsWith(prefix)) return text.slice(prefix.length);
  return text === prefix.trimEnd() ? "" : null;
}

function spec(kind: ToastKind, title: string, text: string): ToastSpec | null {
  const t = clip(text);
  return t ? { kind, title, text: t } : null;
}

/** Prefixes whose lines are progress chatter: they stay in the log only. */
const LOG_ONLY = [
  "RUNNING ·",
  "QUEUED ·",
  "CYCLE ·",
  "LIVE TALK",
  "OBJECTIVE ·",
  "RESEARCH ·",
  "LEARNED ·",
  "CODE ·",
  "COMMITTED ·",
  "EXPERIMENT ·",
  "QUALITY RUN ·",
  "MAINTENANCE ·",
  "FAILOVER ·",
  "RESUMING",
  "FILE ·",
  "GESTURE",
];

/**
 * Maps a HUD `notice` line (components/Syrax.tsx push calls) to a toast, or null when it should stay log-only.
 * Unknown lines (server `notice` events, status chatter) default to log-only: a toast must earn its place.
 */
export function classifyNotice(text: string): ToastSpec | null {
  const line = (text ?? "").trim();
  if (!line) return null;
  if (LOG_ONLY.some((p) => line.startsWith(p))) return null;

  let rest: string | null;
  if ((rest = after(line, "REMINDER · ")) !== null) return spec("reminder", "REMINDER", rest);
  if ((rest = after(line, "CHECK-IN · ")) !== null) return spec("checkin", "CHECK-IN", rest);
  if ((rest = after(line, "SYSTEM ALERT · ")) !== null) return spec("alert", "ALERT", rest);
  if ((rest = after(line, "OBJECTIVE DONE · ")) !== null) return spec("done", "DONE", objective(rest));
  if ((rest = after(line, "OBJECTIVE BLOCKED · ")) !== null) return spec("alert", "BLOCKED", objective(rest));
  if ((rest = after(line, "NEWS · ")) !== null) return spec("news", "NEWS", rest);
  if ((rest = after(line, "CAMERA USED · ")) !== null) return spec("camera", "CAMERA", `Camera used · ${rest}`);
  if ((rest = after(line, "LESSON · ")) !== null) return spec("lesson", "LESSON", rest);
  if ((rest = after(line, "RECOVERED · ")) !== null) return spec("alert", "RECOVERED", `${rest} · see the log`);
  if ((rest = after(line, "ROLLED BACK · ")) !== null) return spec("alert", "ROLLED BACK", rest);
  if ((rest = after(line, "SKILL BUILT · ")) !== null) return spec("done", "SKILL", rest);
  if ((rest = after(line, "SKILL FAILED · ")) !== null) return spec("error", "SKILL FAILED", rest);
  if ((rest = after(line, "PUSHED · ")) !== null) return spec("done", "PUSHED", rest);
  if ((rest = after(line, "PUSH FAILED · ")) !== null) return spec("error", "PUSH FAILED", rest || "push failed");
  if ((rest = after(line, "COMMIT FAILED · ")) !== null) return spec("error", "COMMIT FAILED", rest || "commit failed");
  if (line.startsWith("BENCHMARK · ") || line.startsWith("QUALITY · ")) {
    // only a regression is news; a PASS stays in the log
    if (!/REGRESS/i.test(line)) return null;
    const [head, ...tail] = line.split(" · ");
    return spec("alert", head === "BENCHMARK" ? "BENCHMARK" : "QUALITY", tail.join(" · "));
  }
  if (line.startsWith("AUTONOMY ON")) return spec("info", "AUTONOMY", "On · SYRAX will pursue its own objectives when idle.");
  if (line.startsWith("AUTONOMY OFF")) return spec("info", "AUTONOMY", "Off.");
  if (line.startsWith("BOOT ON")) return spec("info", "BOOT", line.replace(/^BOOT ON · /, "On · "));
  if (line.startsWith("BOOT OFF")) return spec("info", "BOOT", line.replace(/^BOOT OFF · /, "Off · "));
  if (line.startsWith("Memory exported")) return spec("done", "EXPORTED", line);
  return null;
}

/** "#12 · note" → "Objective #12 · note"; an empty note leaves no dangling separator */
function objective(rest: string): string {
  const m = /^#(\S+)\s*·?\s*(.*)$/.exec(rest);
  if (!m) return rest;
  return m[2] ? `Objective #${m[1]} · ${m[2]}` : `Objective #${m[1]}`;
}

/** An `error` log entry as a toast: a "VOICE OUTPUT · …"-style prefix becomes the label. */
export function classifyError(text: string): ToastSpec | null {
  const line = (text ?? "").trim();
  if (!line) return null;
  const m = /^([A-Z][A-Z0-9 -]{1,23}?)(?: ·|:)\s+(.+)$/.exec(line);
  if (m) return spec("error", m[1].trim(), m[2]);
  return spec("error", "ERROR", line);
}
