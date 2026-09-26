"use client";

import type { JournalEvent, TaskDetail, TaskSummary } from "@/lib/syraxClient";

/** HISTORY (what SYRAX did), WHY (one task: goal, steps, checkpoints, lesson) and
 *  TODAY (a replay generated from the real event stream). Read-only. */

export function hhmm(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

const STATUS_TAG: Record<string, string> = {
  SUCCESS: "✓ DONE",
  PARTIAL: "◐ PARTIAL",
  FAILED: "✕ FAILED",
  CANCELLED: "■ CANCELLED",
  INTERRUPTED: "⚡ INTERRUPTED",
  IN_PROGRESS: "▸ RUNNING",
  BLOCKED: "? BLOCKED",
  PENDING: "… PENDING",
  UNKNOWN: "? UNKNOWN",
};

/** One line per event, in words that describe what actually happened. */
export function describeEvent(e: JournalEvent): string | null {
  const p = e.payload as Record<string, unknown>;
  const s = (k: string) => (typeof p[k] === "string" ? (p[k] as string) : "");
  switch (e.type) {
    case "task.started":
      return `Started: ${s("goal").slice(0, 90)}${p["kind"] === "autonomous" ? " (autonomous)" : ""}`;
    case "task.queued":
      return `Queued: ${s("goal").slice(0, 90)}`;
    case "think":
      return null; // too chatty for a replay; visible in WHY
    case "tool.started":
      return `Ran ${s("name")}`;
    case "tool.completed":
      return `${s("name")} ok`;
    case "tool.failed":
      return `${s("name")} FAILED`;
    case "ask":
      return `Asked: ${s("question").slice(0, 90)}`;
    case "answer":
      return `Human answered: ${s("text").slice(0, 60)}`;
    case "final":
      return `Replied: ${s("text").slice(0, 90)}`;
    case "checkpoint.created":
      return `Checkpoint ${p["seq"]} · ${s("stage")}`;
    case "task.completed":
      return `Task ${s("status")}`;
    case "task.failed":
      return `Task FAILED: ${s("error").slice(0, 90)}`;
    case "task.cancelled":
      return "Task cancelled by human";
    case "task.interrupted":
      return `Interrupted at step ${p["step"]} · ${s("recovery_state")}`;
    case "recovery.started":
      return `Recovery started for ${(p["task_ids"] as string[] | undefined)?.length ?? 0} task(s)`;
    case "recovery.verified":
      return "Recovery checked reality";
    case "recovery.resumed":
      return "Resumed interrupted task";
    case "recovery.completed":
      return "Recovery completed";
    case "verification.completed":
      return `Verification ${s("status")}`;
    case "objective.created":
      return `Objective P${p["priority"]}: ${s("goal").slice(0, 90)}`;
    case "objective.completed":
      return `Objective #${p["objective_id"]} done · ${s("note").slice(0, 80)}`;
    case "objective.blocked":
      return `Objective #${p["objective_id"]} blocked · ${s("note").slice(0, 80)}`;
    case "objective.updated":
      return null;
    case "cycle.started":
      return "Autonomous cycle started";
    case "cycle.completed":
      return `Cycle ${s("outcome")}${s("verdict") ? ` · ${s("verdict")}` : ""}${s("reason") ? ` · ${s("reason")}` : ""}`;
    case "reflection.created":
      return `Lesson: ${s("lesson").slice(0, 100)}`;
    case "autonomy.toggled":
      return `Autonomy ${p["enabled"] ? "ON" : "OFF"}`;
    case "code.changed":
      return p["path"] ? `Edited ${s("path")} (${s("command")})` : `Prepared release: ${Object.keys((p["files"] as Record<string, string>) ?? {}).length} file(s)`;
    case "commit.created":
      return `Committed ${s("commit").slice(0, 10)}: ${s("summary").slice(0, 80)}`;
    case "commit.failed":
      return `Commit FAILED: ${s("error").slice(0, 80)}`;
    case "rollback.created":
      return `Rolled back (${s("reason")})`;
    case "push.completed":
      return `Pushed ${s("branch")}`;
    case "push.failed":
      return `Push FAILED`;
    case "push.started":
    case "research.started":
    case "skill.created":
    case "presentation.created":
    case "presentation.dismissed":
      return null;
    case "research.completed":
      return `Researched: ${s("question").slice(0, 70)} · ${p["stored"]} stored`;
    case "knowledge.stored":
      return `Learned (${s("kind")}, ${Math.round(Number(p["confidence"] ?? 0) * 100)}%): ${s("claim").slice(0, 70)}`;
    case "skill.verified":
      return `Skill ${s("skill")} verified (${p["tests_passed"]} tests)`;
    case "skill.failed":
      return `Skill ${s("skill")} FAILED tests`;
    case "benchmark.completed":
      return `Benchmark ${s("status")}${(p["regressions"] as string[] | undefined)?.length ? ` · regressed ${(p["regressions"] as string[]).join(", ")}` : ""}`;
    case "experiment.started":
      return null;
    case "experiment.completed":
      return `Experiment ${s("verdict")}: ${s("hypothesis").slice(0, 70)}`;
    case "maintenance.completed":
      return `Maintenance: pruned ${p["events_pruned"]} events`;
    case "brain.failover":
      return `Brain ${s("provider")} failed over: ${s("reason").slice(0, 60)}`;
    case "brain.answered":
      return null;
    default:
      return e.type;
  }
}

export function HistoryList({ tasks, onOpen }: { tasks: TaskSummary[]; onOpen: (id: string) => void }) {
  if (tasks.length === 0) return <div className="entry entry-notice">No tasks journaled yet.</div>;
  return (
    <>
      {tasks.map((t) => (
        <button key={t.task_id} type="button" className={`hist-row status-${t.status.toLowerCase()}`} onClick={() => onOpen(t.task_id)}>
          <span className="tag">{STATUS_TAG[t.status] ?? t.status}</span>
          <span className="hist-goal">{t.goal}</span>
          <span className="hist-meta">
            {hhmm(t.created)} · {t.kind === "autonomous" ? "AUTO · " : ""}
            {t.current_step} step{t.current_step === 1 ? "" : "s"}
          </span>
        </button>
      ))}
    </>
  );
}

export function WhyView({ detail, onBack, onResume }: { detail: TaskDetail; onBack: () => void; onResume?: (id: string) => void }) {
  const t = detail.task;
  const steps = detail.events.filter(
    (e) =>
      e.type === "tool.started" || e.type === "tool.failed" || e.type === "tool.completed" || e.type === "ask" || e.type === "answer" || e.type === "final" ||
      ["task.", "recovery.", "code.", "commit.", "rollback.", "push.", "research.", "knowledge.", "skill.", "experiment.", "benchmark."].some((pfx) => e.type.startsWith(pfx)),
  );
  const reflection = detail.events.find((e) => e.type === "reflection.created");
  const rec = (t.recovery ?? null) as { state?: string; operation_state?: string; checks?: unknown } | null;
  return (
    <div className="why">
      <button type="button" className="hud-link" onClick={onBack}>
        ← HISTORY
      </button>
      <h4>WHY · {t.task_id}</h4>
      <p>
        <span className="tag">{STATUS_TAG[t.status] ?? t.status}</span>
        {t.goal}
      </p>
      {detail.objective && (
        <p className="why-dim">
          Because of objective #{detail.objective.id} ({detail.objective.source}): {detail.objective.goal.slice(0, 120)}
          {detail.objective.reason ? ` — ${detail.objective.reason}` : ""}
        </p>
      )}
      <h5>WHAT IT DID</h5>
      <ol className="why-steps">
        {steps.map((e) => {
          const line = describeEvent(e);
          return line ? (
            <li key={e.id}>
              <span className="why-ts">{hhmm(e.ts)}</span> {line}
            </li>
          ) : null;
        })}
      </ol>
      <h5>WHAT WAS VERIFIED</h5>
      {detail.checkpoints.length === 0 ? (
        <p className="why-dim">no checkpoint was written</p>
      ) : (
        <ul className="why-steps">
          {detail.checkpoints.map((c) => (
            <li key={c.id}>
              <span className="why-ts">{hhmm(c.ts)}</span> checkpoint {c.seq} · {c.stage} · {c.evidence_state} · {c.completed_steps.length} step(s) · {c.context_messages} messages saved
            </li>
          ))}
        </ul>
      )}
      {rec && (
        <p className="why-dim">
          Recovery: {rec.state} (operation {rec.operation_state})
        </p>
      )}
      <h5>WHAT IT LEARNED</h5>
      <p className={reflection ? "" : "why-dim"}>
        {reflection ? String((reflection.payload as Record<string, unknown>)["lesson"] ?? "") : "no reflection recorded (human tasks are not reflected on yet)"}
      </p>
      <h5>RESULT</h5>
      <p className={t.error ? "why-err" : ""}>{t.result ?? t.error ?? "none recorded"}</p>
      {t.status === "INTERRUPTED" && onResume && (
        <button type="button" className="hud-btn entry-action" onClick={() => onResume(t.task_id)}>
          RESUME
        </button>
      )}
    </div>
  );
}

export function ReplayView({ events }: { events: JournalEvent[] }) {
  const lines = events.map((e) => ({ e, line: describeEvent(e) })).filter((x) => x.line);
  if (lines.length === 0) return <div className="entry entry-notice">Nothing journaled in this window.</div>;
  return (
    <ul className="replay">
      {lines.map(({ e, line }) => (
        <li key={e.id} className={e.type.endsWith(".failed") || e.type === "task.interrupted" ? "replay-bad" : ""}>
          <span className="why-ts">{hhmm(e.ts)}</span> {line}
        </li>
      ))}
    </ul>
  );
}
