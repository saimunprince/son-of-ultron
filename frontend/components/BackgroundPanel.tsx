"use client";

import { useEffect, useState } from "react";
import {
  budgetLine,
  elapsedSeconds,
  isActive,
  sortTasks,
  stateClass,
  stateLabel,
  type BackgroundReport,
  type BackgroundTask,
} from "@/lib/backgroundView";

interface Props {
  items: BackgroundTask[];
  /** Date.now() when `items` arrived: a running task's time counts on from there */
  receivedAt: number;
  report: BackgroundReport | null;
  onRefresh: () => void;
  onCancel: (id: string) => void;
  onFinish: (id: string) => void;
  onReport: (id: string) => void;
  onHideReport: () => void;
  onClose: () => void;
}

/** The background lane (background.py): long read-only research that runs beside the chat. */
export default function BackgroundPanel({ items, receivedAt, report, onRefresh, onCancel, onFinish, onReport, onHideReport, onClose }: Props) {
  const [now, setNow] = useState(() => Date.now());
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const running = items.some(isActive);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);

  // a cancel sent stays "CANCELLING…" until the task's new state arrives
  useEffect(() => {
    setCancelling((c) => {
      const left = new Set([...c].filter((id) => items.some((t) => t.id === id && isActive(t))));
      return left.size === c.size ? c : left;
    });
  }, [items]);

  const cancel = (id: string) => {
    setCancelling((c) => new Set(c).add(id));
    onCancel(id);
  };

  return (
    <div className="brain-backdrop" onClick={onClose}>
      <div className="brain-panel bg-panel" role="dialog" aria-modal="true" aria-labelledby="bg-title" onClick={(e) => e.stopPropagation()}>
        <div className="brain-head">
          <span id="bg-title">// BACKGROUND</span>
          <span className="bg-head-actions">
            <button type="button" className="hud-link" onClick={onRefresh}>
              REFRESH
            </button>
            <button type="button" className="hud-link" onClick={onClose}>
              CLOSE
            </button>
          </span>
        </div>
        <p className="brain-intro">
          Long research that runs beside the chat, so the chat stays free. It can only read the web and stored
          knowledge, and writes its report to its own folder. Ask in the chat, e.g. &ldquo;research X in the background&rdquo;.
        </p>

        {items.length === 0 ? (
          <div className="brain-empty">No background tasks since SYRAX started.</div>
        ) : (
          <ol className="brain-list">
            {sortTasks(items).map((t) => {
              const active = isActive(t);
              const shown = report?.id === t.id ? report : null;
              return (
                <li key={t.id} className={`brain-row bg-row ${stateClass(t.state)}`}>
                  <div className="brain-row-main bg-row-main">
                    <span className="bg-question" title={t.instruction}>
                      {t.instruction}
                    </span>
                    <span className="brain-status" aria-live={active ? "polite" : undefined}>
                      {cancelling.has(t.id) ? "CANCELLING…" : stateLabel(t)}
                    </span>
                  </div>
                  <div className="brain-detail bg-detail">
                    <div className="bg-meta">
                      <span className="brain-tier">{t.id}</span>
                      <span>{budgetLine(t, elapsedSeconds(t, receivedAt, now))}</span>
                      {t.refused > 0 && <span className="brain-note">{t.refused} refused</span>}
                      {t.notes_waiting > 0 && <span className="brain-note">{t.notes_waiting} note(s) waiting</span>}
                    </div>
                    {t.error && <div className="brain-error">{t.error}</div>}
                    <div className="brain-inline">
                      {active && (
                        <>
                          <button type="button" className="hud-btn" disabled={cancelling.has(t.id)} onClick={() => cancel(t.id)}>
                            CANCEL
                          </button>
                          {!t.finishing && (
                            <button type="button" className="hud-link" onClick={() => onFinish(t.id)} title="Stop researching and write the report now">
                              FINISH NOW
                            </button>
                          )}
                        </>
                      )}
                      {t.report &&
                        (shown ? (
                          <button type="button" className="hud-link" aria-expanded="true" onClick={onHideReport}>
                            HIDE REPORT
                          </button>
                        ) : (
                          <button type="button" className="hud-btn" aria-expanded="false" onClick={() => onReport(t.id)}>
                            OPEN REPORT
                          </button>
                        ))}
                      {t.report && (
                        <code className="bg-path" title="Saved report">
                          {t.report}
                        </code>
                      )}
                    </div>
                    {shown &&
                      (shown.error ? (
                        <div className="brain-error" role="alert">
                          {shown.error}
                        </div>
                      ) : shown.text === undefined ? (
                        <div className="brain-note">Reading the report…</div>
                      ) : (
                        <pre className="bg-report" tabIndex={0} aria-label={`Report of ${t.id}`}>
                          {shown.text}
                        </pre>
                      ))}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}
