// Pure helpers for the task progress arc (components/TaskArc.tsx).
import type { TaskPhase } from "./syraxClient";

/** Same order as TASK_PHASES in syraxClient (kept local: tests import no relative values). */
export const ARC_PHASES: readonly TaskPhase[] = ["understand", "plan", "act", "observe", "verify"];

export type SegmentState = "done" | "current" | "todo";

/** Index of a phase in the five-step loop, -1 when unknown or none. */
export function phaseIndex(phase: TaskPhase | null | undefined): number {
  return phase ? ARC_PHASES.indexOf(phase) : -1;
}

/** One state per segment: phases before the current one are done, the current one is lit. */
export function segmentStates(phase: TaskPhase | null | undefined): SegmentState[] {
  const at = phaseIndex(phase);
  return ARC_PHASES.map((_, i) => (at < 0 ? "todo" : i < at ? "done" : i === at ? "current" : "todo"));
}

/** "0:07", "1:23", "12:00", "1:02:03". Negative or invalid input reads as 0:00. */
export function formatElapsed(ms: number): string {
  const total = Number.isFinite(ms) && ms > 0 ? Math.floor(ms / 1000) : 0;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const ss = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/**
 * Shorten to `max` characters. Paths and URLs keep their tail (the file or
 * page is what matters); other text keeps its head.
 */
export function truncate(text: string, max: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  if (max < 2) return t.slice(0, Math.max(max, 0));
  const pathy = /[\\/]/.test(t) && !/\s/.test(t);
  return pathy ? `…${t.slice(-(max - 1))}` : `${t.slice(0, max - 1).trimEnd()}…`;
}

/** "browser · …/docs/index.html": the tool and what it works on, or "" when neither is known. */
export function activityLine(tool: string | null | undefined, target: string | null | undefined, max = 44): string {
  const name = tool?.trim() ?? "";
  const what = target?.trim() ?? "";
  if (!name && !what) return "";
  if (!what) return truncate(name, max);
  if (!name) return truncate(what, max);
  const head = truncate(name, 18);
  return `${head} · ${truncate(what, Math.max(max - head.length - 3, 8))}`;
}

export interface ArcGeometry {
  /** viewBox width */
  width: number;
  /** y of the arc's two ends */
  top: number;
  /** how far the middle of the arc dips below its ends */
  sag: number;
  /** gap between segments, in px along the arc */
  gap: number;
  /** horizontal inset of the arc's ends from the viewBox edges */
  inset: number;
}

export const DEFAULT_ARC: ArcGeometry = { width: 360, top: 4, sag: 12, gap: 6, inset: 14 };

export interface ArcSegment {
  /** SVG path for the segment */
  d: string;
  /** midpoint of the segment, for its label */
  mid: { x: number; y: number };
}

const r2 = (n: number) => Math.round(n * 100) / 100;

/**
 * A shallow smile-shaped arc (it cradles the orb above it) cut into `n` equal
 * segments with gaps. Returns one SVG path per segment, left to right.
 */
export function arcSegments(n: number, g: ArcGeometry = DEFAULT_ARC): ArcSegment[] {
  if (n < 1) return [];
  const half = g.width / 2 - g.inset;
  const radius = (half * half + g.sag * g.sag) / (2 * g.sag);
  const cx = g.width / 2;
  const cy = g.top + g.sag - radius; // the centre sits far above the arc
  const span = 2 * Math.asin(half / radius); // the whole arc, radians
  const step = span / n;
  const gap = Math.min(g.gap / radius, step / 2);
  // θ = 0 is straight down; the left end is -span/2.
  const at = (theta: number) => ({ x: r2(cx + radius * Math.sin(theta)), y: r2(cy + radius * Math.cos(theta)) });
  const R = r2(radius);
  return Array.from({ length: n }, (_, i) => {
    const a = -span / 2 + i * step + (i === 0 ? 0 : gap / 2);
    const b = -span / 2 + (i + 1) * step - (i === n - 1 ? 0 : gap / 2);
    const p = at(a);
    const q = at(b);
    return { d: `M ${p.x} ${p.y} A ${R} ${R} 0 0 0 ${q.x} ${q.y}`, mid: at((a + b) / 2) };
  });
}
