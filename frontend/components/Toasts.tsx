"use client";

/**
 * Notification toasts (2026-11-03): bottom-right, newest nearest the edge, at most three.
 * The countdown IS the hairline's CSS animation: hover or keyboard focus pauses both at once
 * (animation-play-state), and its animationend starts the exit. Hidden tabs throttle it too,
 * so a reminder fired while away is still there when the owner looks back.
 */
import { useEffect, useRef, useState } from "react";

import type { Toast } from "@/lib/toasts";

import styles from "./Toasts.module.css";

const EXIT_MS = 180;

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const [leaving, setLeaving] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const leave = () => {
    if (leaving) return;
    setLeaving(true);
    timer.current = setTimeout(() => onDismiss(toast.id), EXIT_MS);
  };

  const urgent = toast.kind === "error" || toast.kind === "alert";

  return (
    <div
      className={`${styles.card} ${leaving ? styles.leaving : ""}`}
      data-kind={toast.kind}
      role={urgent ? "alert" : "status"}
      onClick={leave}
      title="Click to dismiss"
    >
      <div className={styles.head}>
        <span className={styles.label}>{toast.title}</span>
        <button
          type="button"
          className={styles.close}
          aria-label={`Dismiss ${toast.title.toLowerCase()}`}
          onClick={(e) => {
            e.stopPropagation();
            leave();
          }}
        >
          ×
        </button>
      </div>
      <p className={styles.text}>{toast.text}</p>
      <span
        className={styles.hairline}
        style={{ animationDuration: `${toast.ttlMs}ms` }}
        onAnimationEnd={(e) => {
          e.stopPropagation();
          leave();
        }}
        aria-hidden="true"
      />
    </div>
  );
}

export default function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <section className={styles.stack} aria-label="Notifications" aria-live="polite">
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </section>
  );
}
