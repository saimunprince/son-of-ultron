// What the hands mean: turns each tracked frame into HUD actions (yes, no, hush, mic, console, E-STOP, panel swipes,
// dwell clicks) and live effects (air cursor, drawing, lightning, magnet, storm). Pure apart from the deps it is
// given, so node --test can drive it with made-up frames.

import { Hold, Swipe, type Pose } from "./gestures.ts";

export interface Pt {
  x: number; // mirrored, 0..1 of the frame
  y: number;
}

export interface HandInfo {
  palm: Pt;
  index: Pt; // the index fingertip
  pose: Pose;
  pinching: boolean;
}

export type GestureAction =
  | { kind: "yes" }
  | { kind: "no" }
  | { kind: "hush" }
  | { kind: "mic" }
  | { kind: "console" }
  | { kind: "estop" }
  | { kind: "swipe"; dir: "left" | "right" }
  | { kind: "click"; target: unknown };

export interface ControlDeps {
  /** Screen size in pixels. */
  view(): { w: number; h: number };
  /** The clickable thing under a screen point, or null (dwell-click skips anything marked as not for gestures). */
  pick(x: number, y: number): unknown;
  act(a: GestureAction): void;
  fx?: {
    cursor(at: { x: number; y: number; dwell: number } | null): void;
    draw(x: number, y: number): void;
    arc(a: { x: number; y: number } | null, b?: { x: number; y: number }): void;
    hold(at: { x: number; y: number; progress: number; label: string } | null): void;
    label(text: string, x: number, y: number): void;
  };
  scene?: {
    pulse(strength?: number): void;
    setAttractor(at: { x: number; y: number; strength: number } | null): void;
  };
}

/** How long each pose must be held (ms) and what it does. */
export const HOLDS: Partial<Record<Pose | "estop", { ms: number; action: GestureAction["kind"]; label: string }>> = {
  thumbs_up: { ms: 600, action: "yes", label: "THUMBS UP · YES" },
  thumbs_down: { ms: 600, action: "no", label: "THUMBS DOWN · NO" },
  open: { ms: 1000, action: "hush", label: "PALM · QUIET" },
  two: { ms: 900, action: "mic", label: "TWO · MIC" },
  three: { ms: 900, action: "console", label: "THREE · LOG" },
  estop: { ms: 2000, action: "estop", label: "TWO FISTS · E-STOP" },
};
export const DWELL_MS = 1500;
/** Palm travel per frame (of the frame width) above which the orb stirs. */
export const STORM_SPEED = 0.02;
/** The palm must move less than this per frame for an open-hand hold to count (a wave is not a hold). */
const STILL = 0.012;

export class GestureControl {
  private hold = new Hold();
  private swipe = new Swipe();
  private dwellOn: unknown = null;
  private dwellSince = 0;
  private dwellDone = false;
  private lastPalm: Pt | null = null;

  private deps: ControlDeps;

  constructor(deps: ControlDeps) {
    this.deps = deps;
  }

  frame(hands: HandInfo[], t: number): void {
    const { w, h } = this.deps.view();
    const px = (p: Pt) => ({ x: p.x * w, y: p.y * h });
    const fx = this.deps.fx;
    const main = hands[0] ?? null;

    // storm: a fast-moving hand stirs the orb
    const speed = main && this.lastPalm ? Math.hypot(main.palm.x - this.lastPalm.x, main.palm.y - this.lastPalm.y) : 0;
    this.lastPalm = main ? main.palm : null;
    if (speed > STORM_SPEED) this.deps.scene?.pulse(Math.min(0.25, speed * 4));

    // swipe: an open hand sweeping sideways
    const dir = this.swipe.feed(main && main.pose === "open" ? main.palm.x : null, t);
    if (dir) {
      this.hold.reset();
      this.deps.act({ kind: "swipe", dir });
      const at = px(main!.palm);
      fx?.label(dir === "right" ? "SWIPE ›" : "‹ SWIPE", at.x, at.y);
    }

    // magnet: an open hand pulls the dust; lightning between two open hands
    const open = hands.filter((x) => x.pose === "open");
    this.deps.scene?.setAttractor(open.length ? { ...open[0].palm, strength: 0.6 } : null);
    fx?.arc(open.length >= 2 ? px(open[0].palm) : null, open.length >= 2 ? px(open[1].palm) : undefined);

    // holds: two fists anywhere is the E-STOP; otherwise the main hand's pose
    let key: string | null = null;
    let at: Pt | null = null;
    if (hands.length >= 2 && hands[0].pose === "fist" && hands[1].pose === "fist") {
      key = "estop";
      at = { x: (hands[0].palm.x + hands[1].palm.x) / 2, y: (hands[0].palm.y + hands[1].palm.y) / 2 };
    } else if (main && !main.pinching && HOLDS[main.pose] && main.pose !== "fist") {
      const still = main.pose !== "open" || (speed < STILL && !this.swipe.recent(t));
      key = still ? main.pose : null;
      at = main.palm;
    }
    const rule = key ? HOLDS[key as keyof typeof HOLDS] : undefined;
    const fired = rule ? this.hold.feed(key, t, rule.ms) : this.hold.feed(null, t, 0);
    if (rule && at) {
      const p = px(at);
      fx?.hold(fired ? null : { ...p, progress: this.hold.progress(t, rule.ms), label: rule.label });
      if (fired) {
        fx?.label(rule.label, p.x, p.y - 40);
        this.deps.act({ kind: rule.action } as GestureAction);
      }
    } else {
      fx?.hold(null);
    }

    // point: the index fingertip is an air cursor that draws, and dwelling on a button clicks it
    if (main && main.pose === "point") {
      const tip = px(main.index);
      fx?.draw(tip.x, tip.y);
      const target = this.deps.pick(tip.x, tip.y);
      if (target !== this.dwellOn) {
        this.dwellOn = target;
        this.dwellSince = t;
        this.dwellDone = false;
      }
      const dwell = target && !this.dwellDone ? Math.min(1, (t - this.dwellSince) / DWELL_MS) : 0;
      fx?.cursor({ ...tip, dwell });
      if (target && !this.dwellDone && dwell >= 1) {
        this.dwellDone = true;
        this.deps.act({ kind: "click", target });
        fx?.label("CLICK", tip.x, tip.y - 24);
      }
    } else {
      this.dwellOn = null;
      this.dwellDone = false;
      fx?.cursor(null);
    }
  }

  /** The hands left the frame or tracking stopped: let go of everything. */
  clear(): void {
    this.hold.reset();
    this.dwellOn = null;
    this.lastPalm = null;
    this.swipe.feed(null, 0);
    this.deps.fx?.cursor(null);
    this.deps.fx?.arc(null);
    this.deps.fx?.hold(null);
    this.deps.scene?.setAttractor(null);
  }
}
