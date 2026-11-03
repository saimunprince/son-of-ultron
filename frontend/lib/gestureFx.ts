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
  dispose(): void;
}

const SPARKS = 90;

export function createGestureFx(canvas: HTMLCanvasElement): GestureFx {
  const ctx = canvas.getContext("2d");
  const reduced = typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const rings: Ring[] = [];
  const sparks: Spark[] = [];
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

    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
    ctx.globalCompositeOperation = "source-over";
    if (rings.length || sparks.length) raf = requestAnimationFrame(frame);
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
    dispose() {
      disposed = true;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", fit);
      rings.length = 0;
      sparks.length = 0;
      ctx?.clearRect(0, 0, canvas.width, canvas.height);
    },
  };
}
