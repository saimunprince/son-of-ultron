// Pure hand-gesture math, kept apart from MediaPipe so it can be tested with plain points.

export interface HandPoint {
  x: number;
  y: number;
}

// MediaPipe hand landmarks
export const WRIST = 0;
export const MIDDLE_MCP = 9;
const FINGER_TIPS = [8, 12, 16, 20];

/** The 21-point hand skeleton as landmark index pairs (thumb, four fingers, palm). */
export const HAND_CONNECTIONS: ReadonlyArray<readonly [number, number]> = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
];

// Fist hysteresis on reach: fingertip-to-wrist distance in palm lengths. An open hand is about 1.9, a fist about 0.9.
export const FIST_ON = 1.2;
export const FIST_OFF = 1.5;
/** A fist fires at most once per this long, so a held fist is one burst. */
export const FIST_COOLDOWN_MS = 900;

function dist(a: HandPoint, b: HandPoint): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** How far the fingertips reach from the wrist, in palm lengths (wrist to middle knuckle); null without a palm. */
export function reach(lm: ReadonlyArray<HandPoint>): number | null {
  const palm = dist(lm[WRIST], lm[MIDDLE_MCP]);
  if (palm < 1e-6) return null;
  const sum = FINGER_TIPS.reduce((s, i) => s + dist(lm[i], lm[WRIST]), 0);
  return sum / FINGER_TIPS.length / palm;
}

/** Whether the hand is a fist now, given whether it was one: on below FIST_ON, off above FIST_OFF. */
export function isFist(lm: ReadonlyArray<HandPoint>, was: boolean): boolean {
  const r = reach(lm);
  if (r === null) return was;
  return was ? r < FIST_OFF : r < FIST_ON;
}

/** Whether a fist that just closed should fire, given when the last one fired. */
export function fistFires(was: boolean, now: boolean, lastAt: number, t: number): boolean {
  return now && !was && t - lastAt >= FIST_COOLDOWN_MS;
}

/** The middle of the palm, for where an effect starts. */
export function palmCenter(lm: ReadonlyArray<HandPoint>): HandPoint {
  return { x: (lm[WRIST].x + lm[MIDDLE_MCP].x) / 2, y: (lm[WRIST].y + lm[MIDDLE_MCP].y) / 2 };
}

// ——— Poses: which fingers are out ———

const FINGERS: ReadonlyArray<readonly [number, number]> = [
  [8, 6], // index: tip, middle joint
  [12, 10],
  [16, 14],
  [20, 18],
];
const THUMB_TIP = 4;
const THUMB_MCP = 2;
const INDEX_MCP = 5;

export type Pose = "fist" | "open" | "point" | "two" | "three" | "thumbs_up" | "thumbs_down" | "other";

/** Which of index, middle, ring and little are stretched out: the tip is clearly farther from the wrist than its middle joint. */
export function fingersOut(lm: ReadonlyArray<HandPoint>): boolean[] {
  return FINGERS.map(([tip, pip]) => dist(lm[tip], lm[WRIST]) > dist(lm[pip], lm[WRIST]) * 1.15);
}

/** Whether the thumb sticks out: its tip is away from the index and middle middle joints (in a fist it rests on
 * them) and away from its own base. */
export function thumbOut(lm: ReadonlyArray<HandPoint>): boolean {
  const palm = dist(lm[WRIST], lm[MIDDLE_MCP]);
  if (palm < 1e-6) return false;
  const off = Math.min(dist(lm[THUMB_TIP], lm[6]), dist(lm[THUMB_TIP], lm[10]), dist(lm[THUMB_TIP], lm[INDEX_MCP]));
  return off / palm > 0.6 && dist(lm[THUMB_TIP], lm[THUMB_MCP]) / palm > 0.5;
}

/** The hand's pose. Image y grows downwards, so a thumb up has the smaller y. */
export function pose(lm: ReadonlyArray<HandPoint>): Pose {
  const palm = dist(lm[WRIST], lm[MIDDLE_MCP]);
  if (palm < 1e-6) return "other";
  const [i, m, r, l] = fingersOut(lm);
  const n = [i, m, r, l].filter(Boolean).length;
  if (n === 0) {
    if (thumbOut(lm)) {
      const rise = (lm[THUMB_MCP].y - lm[THUMB_TIP].y) / palm;
      if (rise > 0.5) return "thumbs_up";
      if (rise < -0.5) return "thumbs_down";
      return "other";
    }
    return "fist";
  }
  if (n === 4) return "open";
  if (i && !m && !r && !l) return "point";
  if (i && m && !r && !l) return "two";
  if (i && m && r && !l) return "three";
  return "other";
}

/** Fires once when the same key has been held for its time; holding on never fires again until the key changes. */
export class Hold {
  private key: string | null = null;
  private since = 0;
  private fired = false;

  /** Feed the current key (null: nothing held) at time t (ms); returns the key the moment its hold completes. */
  feed(key: string | null, t: number, ms: number): string | null {
    if (key !== this.key) {
      this.key = key;
      this.since = t;
      this.fired = false;
      return null;
    }
    if (key === null || this.fired || t - this.since < ms) return null;
    this.fired = true;
    return key;
  }

  /** 0..1: how far the current hold has come (for a progress ring). */
  progress(t: number, ms: number): number {
    if (this.key === null || this.fired) return 0;
    return Math.max(0, Math.min(1, (t - this.since) / ms));
  }

  reset(): void {
    this.key = null;
    this.fired = false;
  }
}

/** A quick sideways sweep of the open hand: "left" or "right" (as the human sees it), at most once per cooldown. */
export class Swipe {
  private trail: { x: number; t: number }[] = [];
  private lastAt = -Infinity;

  static readonly WINDOW_MS = 280;
  static readonly DISTANCE = 0.22; // of the frame width
  static readonly COOLDOWN_MS = 900;

  /** Feed the palm's mirrored x (0..1) at time t, or null when no open hand is seen. */
  feed(x: number | null, t: number): "left" | "right" | null {
    if (x === null) {
      this.trail = [];
      return null;
    }
    this.trail.push({ x, t });
    while (this.trail.length && t - this.trail[0].t > Swipe.WINDOW_MS) this.trail.shift();
    if (t - this.lastAt < Swipe.COOLDOWN_MS || this.trail.length < 3) return null;
    const dx = x - this.trail[0].x;
    if (Math.abs(dx) < Swipe.DISTANCE) return null;
    this.lastAt = t;
    this.trail = [];
    return dx > 0 ? "right" : "left";
  }

  /** Whether a swipe just happened (the hand should not also count as held still). */
  recent(t: number): boolean {
    return t - this.lastAt < Swipe.COOLDOWN_MS;
  }
}

/** The next panel in the swipe cycle: none, BRAIN, SELF, MIND, and round again. */
export type Panel = "none" | "brain" | "self" | "mind";
const PANELS: Panel[] = ["none", "brain", "self", "mind"];
export function nextPanel(now: Panel, dir: "left" | "right"): Panel {
  const i = PANELS.indexOf(now);
  return PANELS[(i + (dir === "right" ? 1 : PANELS.length - 1)) % PANELS.length];
}
