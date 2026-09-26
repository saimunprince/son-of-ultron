"use client";

import { useEffect } from "react";
import type { SelfModelSummary } from "@/lib/syraxClient";

interface Props {
  model: SelfModelSummary | null;
  onRefresh: () => void;
  onClose: () => void;
}

function ago(ts: number | null | undefined): string {
  if (!ts) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** Read-only view of SYRAX's evidence-based self-model. The frontend draws; it never decides. */
export default function SelfPanel({ model, onRefresh, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const statuses = model ? Object.entries(model.tasks_by_status) : [];
  const mem = model?.runtime.memory_mb;

  return (
    <div className="brain-backdrop" onClick={onClose}>
      <div className="brain-panel self-panel" onClick={(e) => e.stopPropagation()}>
        <div className="brain-head">
          <span>// SELF MODEL</span>
          <span className="self-version">
            {model ? `${model.identity.name} · ${model.identity.version ?? "version unknown"}` : "LOADING…"}
          </span>
        </div>
        {!model ? (
          <div className="brain-empty">Reading the journal…</div>
        ) : (
          <div className="brain-list self-body">
            <section>
              <h4>STAGE</h4>
              <p>{model.identity.stage}</p>
              <p className="self-dim">
                boot {model.identity.boot_id} · up {model.identity.process_uptime_s}s · CPU load{" "}
                {model.runtime.cpu.load_1_5_15?.join(" / ") ?? "?"} on {model.runtime.cpu.cores ?? "?"} cores · RAM{" "}
                {mem?.available_mb != null && mem.total_mb != null ? `${mem.total_mb - mem.available_mb} / ${mem.total_mb} MB` : "?"}
                {model.runtime.brains ? ` · brain ${model.runtime.brains.active ?? "none yet"} (${model.runtime.brains.ready.length} ready)` : ""}
              </p>
              <p className="self-dim">
                {model.runtime.battery ? `battery ${model.runtime.battery.percent}% ${model.runtime.battery.status}` : "no battery"}
                {model.runtime.quiet_hours?.window ? ` · quiet ${model.runtime.quiet_hours.window[0]}:00-${model.runtime.quiet_hours.window[1]}:00${model.runtime.quiet_hours.active ? " (now)" : ""}` : ""}
                {model.runtime.pressure ? ` · PAUSED: ${model.runtime.pressure}` : " · resources ok"}
              </p>
            </section>
            <section>
              <h4>TASKS</h4>
              <p>
                {statuses.length === 0
                  ? "no tasks journaled yet"
                  : statuses.map(([k, v]) => `${k} ${v}`).join(" · ")}
                {model.success_rate != null ? ` · success ${Math.round(model.success_rate * 100)}%` : ""}
              </p>
              {model.running_task && <p>RUNNING · {model.running_task.goal} · step {model.running_task.step}</p>}
              {model.interrupted.map((t) => (
                <p key={t.task_id} className="self-warn">
                  INTERRUPTED · {t.goal} · step {t.step} · {t.recovery_state ?? "?"}
                </p>
              ))}
              <p className="self-dim">
                last verification:{" "}
                {model.last_verification
                  ? `${model.last_verification.status} (${model.last_verification.git_head?.slice(0, 7) ?? "?"}, ${ago(model.last_verification.ts)})`
                  : "none recorded"}
              </p>
            </section>
            <section>
              <h4>CAPABILITIES (evidence from the journal)</h4>
              <table className="self-table">
                <tbody>
                  {model.capabilities.map((c) => (
                    <tr key={c.capability} className={`cap-${c.status.toLowerCase()}`}>
                      <td>{c.capability}</td>
                      <td>{c.status}</td>
                      <td>{c.uses} use{c.uses === 1 ? "" : "s"}</td>
                      <td>{c.confidence == null ? "—" : `${Math.round(c.confidence * 100)}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            <section>
              <h4>PERFORMANCE (measured)</h4>
              <p className={model.performance.last_benchmark?.status === "REGRESSION" ? "self-warn" : ""}>
                {model.performance.last_benchmark
                  ? `benchmark #${model.performance.last_benchmark.id} ${model.performance.last_benchmark.status} · ${ago(model.performance.last_benchmark.ts)} · ` +
                    Object.entries(model.performance.last_benchmark.metrics).map(([k, v]) => `${k.replace(/_ms$/, "")} ${v}ms`).join(" · ")
                  : "no benchmark recorded yet"}
              </p>
              <p className="self-dim">
                {model.performance.experiments.count} experiment(s)
                {model.performance.experiments.recent.length ? ` · last: ${model.performance.experiments.recent[0].verdict} — ${model.performance.experiments.recent[0].hypothesis.slice(0, 60)}` : ""}
              </p>
            </section>
            <section>
              <h4>WEAKNESSES</h4>
              {model.weaknesses.length === 0 ? (
                <p className="self-dim">none derived from evidence</p>
              ) : (
                model.weaknesses.map((w, i) => (
                  <p key={i}>
                    <span className="self-kind">{w.kind}</span> {w.detail}
                  </p>
                ))
              )}
              <p className="self-dim">
                {model.known_limitations} known limitations documented in the system map · {model.knowledge_count} knowledge entries stored.
              </p>
            </section>
          </div>
        )}
        <div className="brain-foot">
          <button type="button" className="hud-btn" onClick={onRefresh}>
            REFRESH
          </button>
          <button type="button" className="hud-btn" onClick={onClose}>
            CLOSE
          </button>
        </div>
      </div>
    </div>
  );
}
