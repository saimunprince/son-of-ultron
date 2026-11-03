"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

import { planCaption } from "@/lib/captions";
import styles from "./Captions.module.css";

/** Cross-fade overlap between two chunks, and the final fade-out (match the CSS). */
const CROSSFADE_MS = 420;
const FADE_OUT_MS = 650;

type Line = { key: number; text: string; ms: number; last: boolean };
type View = { lines: Line[]; current: number; leaving: number | null; closing: boolean; truncated: boolean };

const EMPTY: View = { lines: [], current: -1, leaving: null, closing: false, truncated: false };

/**
 * Film-style captions above the command bar. Each new `nonce` with a non-empty
 * `text` plays that answer as a short run of timed chunks, cancelling any run
 * already on screen. Decorative only: the full text is in the log.
 */
export default function Captions({ text, nonce, enabled }: { text: string | null; nonce: number; enabled: boolean }) {
  const [view, setView] = useState<View>(EMPTY);
  // The nonce that was current while captions were off: switching them back on
  // must not replay that answer. (Idempotent, so StrictMode's double run is safe.)
  const offNonce = useRef<number | null>(null);

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    const at = (ms: number, fn: () => void) => timers.push(setTimeout(fn, ms));
    if (!enabled) offNonce.current = nonce;
    const plan = enabled && text && offNonce.current !== nonce ? planCaption(text) : null;

    if (!plan || plan.chunks.length === 0) {
      at(0, () => setView((v) => (v.lines.length ? { ...v, closing: true } : v)));
      at(FADE_OUT_MS, () => setView(EMPTY));
    } else {
      const lines: Line[] = plan.chunks.map((t, i) => ({
        key: nonce * 100 + i,
        text: t,
        ms: plan.durations[i],
        last: i === plan.chunks.length - 1,
      }));
      at(0, () => setView({ lines, current: 0, leaving: null, closing: false, truncated: plan.truncated }));
      let t = 0;
      for (let i = 1; i < lines.length; i++) {
        t += lines[i - 1].ms;
        at(t, () => setView((v) => ({ ...v, current: i, leaving: i - 1 })));
        at(t + CROSSFADE_MS, () => setView((v) => (v.leaving === i - 1 ? { ...v, leaving: null } : v)));
      }
      t += lines[lines.length - 1].ms;
      at(t, () => setView((v) => ({ ...v, closing: true })));
      at(t + FADE_OUT_MS, () => setView(EMPTY));
    }
    return () => timers.forEach(clearTimeout);
    // Replays are keyed on `nonce`; `text` arrives with it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, enabled]);

  if (view.lines.length === 0) return null;
  const shown = [view.leaving, view.current].filter((i): i is number => i !== null && i >= 0);

  return (
    <div className={`${styles.captions}${view.closing ? ` ${styles.closing}` : ""}`} aria-hidden="true">
      <div className={styles.label}>SYRAX</div>
      <div className={styles.stack}>
        {shown.map((i) => {
          const line = view.lines[i];
          const leaving = i === view.leaving;
          return (
            <p
              key={line.key}
              className={`${styles.line}${leaving ? ` ${styles.leaving}` : ""}`}
              style={{ "--cap-ms": `${line.ms}ms` } as CSSProperties}
            >
              {line.text}
              {line.last && view.truncated ? <span className={styles.more}>…</span> : null}
            </p>
          );
        })}
      </div>
      <div className={styles.rule}>
        <span key={view.lines[view.current]?.key} className={styles.progress} style={{ "--cap-ms": `${view.lines[view.current]?.ms ?? 0}ms` } as CSSProperties} />
      </div>
    </div>
  );
}
