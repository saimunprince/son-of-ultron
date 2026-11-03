// Full-screen 2D effects for hand gestures, drawn over the orb: a shockwave ring where a pinch starts, and a
// power burst of sparks from the orb when a fist closes. The canvas animates only while an effect is alive.

interface Ring {
  x: number;
  y: number;
  r: number;
  max: number;
  life: number;
}

interface Spark {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
}

export interface GestureFx {
  /** A shockwave ring at screen pixels (x, y); strength scales its size. */
  ripple(x: number, y: number, strength?: number): void;
  /** A burst of sparks and a double ring from screen pixels (x, y). */
  burst(x: number, y: number): void;
  /** The air cursor at (x, y) with its dwell progress 0..1, or null to hide it. */
  cursor(at: { x: number; y: number; dwell: number } | null): void;
  /** Adds a point to the air-drawing trail (it fades by itself). */
  draw(x: number, y: number): void;
  /** A lightning arc between two points, or null for none. */
  arc(a: { x: number; y: number } | null, b?: { x: number; y: number }): void;
  /** A hold-progress ring at (x, y) with a label, or null to hide it. */
  hold(at: { x: number; y: number; progress: number; label: string } | null): void;
  /** A short label that floats up and fades, e.g. "THUMBS UP · YES". */
  label(text: string, x: number, y: number): void;
  dispose(): void;
}

interface Ink {
  x: number;
  y: number;
  life: number;
}

interface Tag {
  text: string;
  x: number;
  y: number;
  life: number;
}

const SPARKS = 90;

export function createGestureFx(canvas: HTMLCanvasElement): GestureFx {
  const ctx = canvas.getContext("2d");
  const reduced = typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const rings: Ring[] = [];
  const sparks: Spark[] = [];
  const ink: Ink[] = [];
  const tags: Tag[] = [];
  let pointer: { x: number; y: number; dwell: number } | null = null;
  let bolt: { a: { x: number; y: number }; b: { x: number; y: number } } | null = null;
  let ring: { x: number; y: number; progress: number; label: string } | null = null;
  let raf = 0;
  let disposed = false;

  const fit = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(window.innerWidth * dpr);
    canvas.height = Math.round(window.innerHeight * dpr);
    ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  fit();
  window.addEventListener("resize", fit);

  const colors = () => {
    const css = getComputedStyle(document.documentElement);
    return {
      hot: css.getPropertyValue("--accent-hot").trim() || "#ff6b5e",
      line: css.getPropertyValue("--line-rgb").trim() || "220 226 235",
    };
  };

  const frame = () => {
    raf = 0;
    if (disposed || !ctx) return;
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    const { hot, line } = colors();
    ctx.globalCompositeOperation = "lighter";

    for (let i = rings.length - 1; i >= 0; i--) {
      const g = rings[i];
      g.life -= 0.022;
      g.r += (g.max - g.r) * 0.085;
      if (g.life <= 0) {
        rings.splice(i, 1);
        continue;
      }
      ctx.globalAlpha = g.life;
      ctx.strokeStyle = hot;
      ctx.shadowColor = hot;
      ctx.shadowBlur = 18;
      ctx.lineWidth = 1 + 3 * g.life;
      ctx.beginPath();
      ctx.arc(g.x, g.y, g.r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.strokeStyle = `rgb(${line} / 0.6)`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(g.x, g.y, g.r * 0.72, 0, Math.PI * 2);
      ctx.stroke();
    }

    ctx.shadowBlur = 10;
    for (let i = sparks.length - 1; i >= 0; i--) {
      const s = sparks[i];
      s.life -= 0.018;
      if (s.life <= 0) {
        sparks.splice(i, 1);
        continue;
      }
      const px = s.x;
      const py = s.y;
      s.x += s.vx;
      s.y += s.vy;
      s.vx *= 0.965;
      s.vy *= 0.965;
      ctx.globalAlpha = s.life;
      ctx.strokeStyle = s.life > 0.55 ? hot : `rgb(${line})`;
      ctx.shadowColor = hot;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(px, py);
      ctx.lineTo(s.x, s.y);
      ctx.stroke();
    }

    // the air-drawing trail: a fading neon line through the points, oldest first
    for (let i = ink.length - 1; i >= 0; i--) {
      ink[i].life -= 0.012;
      if (ink[i].life <= 0) ink.splice(i, 1);
    }
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.shadowColor = hot;
    ctx.shadowBlur = 14;
    for (let i = 1; i < ink.length; i++) {
      const p = ink[i - 1];
      const q = ink[i];
      if (Math.hypot(q.x - p.x, q.y - p.y) > 160) continue; // a jump (the finger left and came back) is not a stroke
      ctx.globalAlpha = Math.min(p.life, q.life);
      ctx.strokeStyle = hot;
      ctx.lineWidth = 2 + 3 * q.life;
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(q.x, q.y);
      ctx.stroke();
    }

    if (bolt) {
      // a new jagged path every frame reads as crackling lightning
      const { a, b } = bolt;
      const len = Math.hypot(b.x - a.x, b.y - a.y);
      const steps = Math.max(6, Math.round(len / 24));
      const nx = -(b.y - a.y) / (len || 1);
      const ny = (b.x - a.x) / (len || 1);
      for (const [w, alpha, color] of [[5, 0.35, hot], [1.6, 0.95, `rgb(${line})`]] as const) {
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = color;
        ctx.lineWidth = w;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        for (let i = 1; i < steps; i++) {
          const f = i / steps;
          const jitter = (Math.random() - 0.5) * Math.min(46, len * 0.12);
          ctx.lineTo(a.x + (b.x - a.x) * f + nx * jitter, a.y + (b.y - a.y) * f + ny * jitter);
        }
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
    }

    if (pointer) {
      ctx.globalAlpha = 1;
      ctx.strokeStyle = hot;
      ctx.lineWidth = 1.5;
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.arc(pointer.x, pointer.y, 10, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = `rgb(${line})`;
      ctx.beginPath();
      ctx.arc(pointer.x, pointer.y, 2.5, 0, Math.PI * 2);
      ctx.fill();
      if (pointer.dwell > 0) {
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(pointer.x, pointer.y, 16, -Math.PI / 2, -Math.PI / 2 + pointer.dwell * Math.PI * 2);
        ctx.stroke();
      }
    }

    if (ring && ring.progress > 0) {
      ctx.globalAlpha = 0.9;
      ctx.strokeStyle = hot;
      ctx.lineWidth = 4;
      ctx.shadowBlur = 16;
      ctx.beginPath();
      ctx.arc(ring.x, ring.y, 34, -Math.PI / 2, -Math.PI / 2 + ring.progress * Math.PI * 2);
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.fillStyle = `rgb(${line})`;
      ctx.font = "600 11px ui-monospace, monospace";
      ctx.textAlign = "center";
      ctx.fillText(ring.label, ring.x, ring.y + 54);
    }

    ctx.shadowBlur = 0;
    ctx.font = "700 14px ui-monospace, monospace";
    ctx.textAlign = "center";
    for (let i = tags.length - 1; i >= 0; i--) {
      const g = tags[i];
      g.life -= 0.012;
      g.y -= 0.5;
      if (g.life <= 0) {
        tags.splice(i, 1);
        continue;
      }
      ctx.globalAlpha = Math.min(1, g.life * 1.5);
      ctx.fillStyle = hot;
      ctx.fillText(g.text, g.x, g.y);
    }

    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
    ctx.globalCompositeOperation = "source-over";
    if (rings.length || sparks.length || ink.length || tags.length || pointer || bolt || (ring && ring.progress > 0)) {
      raf = requestAnimationFrame(frame);
    }
  };

  const wake = () => {
    if (!raf && !disposed) raf = requestAnimationFrame(frame);
  };

  return {
    ripple(x, y, strength = 1) {
      if (reduced || disposed) return;
      rings.push({ x, y, r: 6, max: 70 + 110 * strength, life: 1 });
      wake();
    },
    burst(x, y) {
      if (reduced || disposed) return;
      const span = Math.min(window.innerWidth, window.innerHeight);
      rings.push({ x, y, r: 20, max: span * 0.42, life: 1 }, { x, y, r: 10, max: span * 0.28, life: 0.8 });
      for (let i = 0; i < SPARKS; i++) {
        const a = Math.random() * Math.PI * 2;
        const v = 4 + Math.random() * 11;
        sparks.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: 0.7 + Math.random() * 0.3 });
      }
      wake();
    },
    cursor(at) {
      pointer = at;
      wake();
    },
    draw(x, y) {
      if (reduced || disposed) return;
      ink.push({ x, y, life: 1 });
      if (ink.length > 240) ink.shift();
      wake();
    },
    arc(a, b) {
      bolt = !reduced && a && b ? { a, b } : null;
      wake();
    },
    hold(at) {
      ring = at;
      wake();
    },
    label(text, x, y) {
      if (disposed) return;
      tags.push({ text, x, y, life: 1 });
      wake();
    },
    dispose() {
      disposed = true;
      ink.length = 0;
      tags.length = 0;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", fit);
      rings.length = 0;
      sparks.length = 0;
      ctx?.clearRect(0, 0, canvas.width, canvas.height);
    },
  };
}
