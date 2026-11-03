"use client";

import { useEffect, useState } from "react";

import type { TaskPhase } from "@/lib/syraxClient";
import { ARC_PHASES, activityLine, arcSegments, DEFAULT_ARC, formatElapsed, phaseIndex, segmentStates } from "@/lib/taskArc";

import styles from "./TaskArc.module.css";

const SEGMENTS = arcSegments(ARC_PHASES.length);
const TRACK = arcSegments(1, { ...DEFAULT_ARC, gap: 0 })[0];
const VIEW_H = 34;

export interface TaskArcProps {
  /** A task is running (agent state is "thinking" or "acting"). False fades the arc out. */
  active: boolean;
  phase: TaskPhase | null;
  step: number | null;
  tool: string | null;
  target: string | null;
  /** Date.now() when the task started; drives the ticking clock. */
  startedAt: number | null;
  /** Distance from the viewport bottom in px (default 160: above the caption line and the command bar). */
  bottom?: number;
}

interface Snapshot {
  phase: TaskPhase | null;
  step: number | null;
  tool: string | null;
  target: string | null;
  startedAt: number | null;
}

/** A thin five-segment arc under the orb: the task loop, the step, the clock and the current tool. */
export default function TaskArc({ active, phase, step, tool, target, startedAt, bottom = 160 }: TaskArcProps) {
  // Keep the last live picture so the arc fades out showing what it showed, not blanks.
  const [shown, setShown] = useState<Snapshot>({ phase, step, tool, target, startedAt });
  if (
    active &&
    (shown.phase !== phase || shown.step !== step || shown.tool !== tool || shown.target !== target || shown.startedAt !== startedAt)
  ) {
    setShown({ phase, step, tool, target, startedAt });
  }
  const view: Snapshot = active ? { phase, step, tool, target, startedAt } : shown;

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active || startedAt == null) return;
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, 500);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [active, startedAt]);

  const states = segmentStates(view.phase);
  const at = phaseIndex(view.phase);
  const activity = activityLine(view.tool, view.target);

  return (
    <div
      className={styles.root}
      data-active={active ? "true" : "false"}
      style={{ bottom }}
      role="progressbar"
      aria-hidden={!active}
      aria-label="task progress"
      aria-valuemin={0}
      aria-valuemax={ARC_PHASES.length}
      aria-valuenow={at + 1}
      aria-valuetext={view.phase ? `${view.phase}${view.step != null ? `, step ${view.step}` : ""}` : "starting"}
    >
      <svg className={styles.arc} viewBox={`0 0 ${DEFAULT_ARC.width} ${VIEW_H}`} aria-hidden="true">
        <path className={styles.track} d={TRACK.d} />
        {SEGMENTS.map((s, i) => (
          <g key={ARC_PHASES[i]} className={styles.seg} data-state={states[i]}>
            <path className={styles.segLine} d={s.d} />
            {states[i] === "current" && <path className={styles.sweep} d={s.d} pathLength={100} />}
            <text className={styles.label} x={s.mid.x} y={s.mid.y + 13} textAnchor="middle">
              {ARC_PHASES[i].toUpperCase()}
            </text>
          </g>
        ))}
      </svg>
      <div className={styles.meta}>
        {view.step != null && <span className={styles.step}>STEP {view.step}</span>}
        {view.startedAt != null && (
          <span className={styles.clock}>{formatElapsed((active ? now : Math.max(now, view.startedAt)) - view.startedAt)}</span>
        )}
        {activity && (
          <span className={styles.activity} title={[view.tool, view.target].filter(Boolean).join(" · ")}>
            {activity}
          </span>
        )}
      </div>
    </div>
  );
}
