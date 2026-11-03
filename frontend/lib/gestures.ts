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
