"use client";

import { failoverText, formatLatency, latencyTone, shortModel } from "@/lib/brainChip";

import styles from "./BrainChip.module.css";

export interface BrainFailover {
  /** provider id that failed, e.g. "gemini" */
  from: string;
  reason: string;
  /** Date.now() when the failover event arrived; a new value replays the 3 s warning. */
  at: number;
}

export interface BrainChipProps {
  /** Provider label of the brain that answered last, e.g. "Gemini". */
  label: string | null;
  model: string | null;
  /** Last measured brain latency in ms (client-side, see createLatencyTracker). */
  ms: number | null;
  failover: BrainFailover | null;
  /** Optional: open the brain settings. Without it the chip is plain text. */
  onClick?: () => void;
}

/** Which brain answers now, its model and its last latency; flashes a failover for 3 s. */
export default function BrainChip({ label, model, ms, failover, onClick }: BrainChipProps) {
  if (!label && !failover) return null;
  const short = shortModel(model);
  const latency = formatLatency(ms);
  const title = [label, model, latency && `last answer ${latency}`].filter(Boolean).join(" · ");

  const body = (
    <>
      <span className={styles.dot} data-tone={latencyTone(ms)} key={ms ?? "none"} aria-hidden="true" />
      <span className={styles.label}>{label ? label.toUpperCase() : "BRAIN"}</span>
      {short && <span className={styles.model}>{short}</span>}
      {latency && <span className={styles.ms}>{latency}</span>}
    </>
  );

  return (
    <div className={styles.root}>
      {label &&
        (onClick ? (
          <button type="button" className={styles.chip} onClick={onClick} title={title}>
            {body}
          </button>
        ) : (
          <div className={styles.chip} title={title}>
            {body}
          </div>
        ))}
      {failover && (
        <div key={failover.at} className={styles.failover} role="status" title={failover.reason}>
          {failoverText(failover.from, label)}
        </div>
      )}
    </div>
  );
}
