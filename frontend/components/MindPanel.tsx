"use client";

import { useEffect, useState } from "react";
import type { BrainScore, ClientMessage, Objective, ObjectiveStatus, Proposal, SkillRow } from "@/lib/syraxClient";

export type MindTab = "briefing" | "objectives" | "proposals" | "skills" | "brains";

export interface MindData {
  briefing: string | null;
  objectives: Objective[] | null;
  proposals: Proposal[] | null;
  skills: SkillRow[] | null;
  scorecard: Record<string, BrainScore> | null;
}

interface Props {
  tab: MindTab;
  data: MindData;
  onTab: (tab: MindTab) => void;
  send: (msg: ClientMessage) => void;
  onClose: () => void;
}

const TABS: [MindTab, string][] = [
  ["briefing", "BRIEFING"],
  ["objectives", "OBJECTIVES"],
  ["proposals", "PROPOSALS"],
  ["skills", "SKILLS"],
  ["brains", "BRAINS"],
];

/** What each tab asks the backend for. */
export function mindRequest(tab: MindTab): ClientMessage {
  switch (tab) {
    case "briefing":
      return { type: "briefing", hours: 24 };
    case "objectives":
      return { type: "objectives", limit: 50 };
    case "proposals":
      return { type: "proposals", limit: 10 };
    case "skills":
      return { type: "skills" };
    case "brains":
      return { type: "self_model", section: "brains" };
  }
}

const STATUS_ORDER: ObjectiveStatus[] = ["ACTIVE", "OPEN", "BLOCKED", "DONE", "DROPPED"];

function ago(ts: number | null | undefined): string {
  if (!ts) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

/** SYRAX's own mind: what it did, is pursuing, proposes, has learned, and how its brains perform.
 *  The frontend draws and forwards the human's decisions; the backend judges. */
export default function MindPanel({ tab, data, onTab, send, onClose }: Props) {
  const [showClosed, setShowClosed] = useState(false);
  const [pending, setPending] = useState<{ id: number; status: "OPEN" | "DROPPED" } | null>(null);
  const [note, setNote] = useState("");
  const [goal, setGoal] = useState("");
  const [priority, setPriority] = useState(3);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const refresh = () => send(mindRequest(tab));

  const decide = () => {
    if (!pending || !note.trim()) return;
    send({ type: "objective_update", id: pending.id, status: pending.status, note: note.trim() });
    setPending(null);
    setNote("");
    setTimeout(refresh, 400);
  };

  const addObjective = () => {
    if (!goal.trim()) return;
    send({ type: "objective_add", goal: goal.trim(), priority });
    setGoal("");
    setTimeout(refresh, 400);
  };

  const objectives = data.objectives ?? [];
  const live = objectives.filter((o) => !["DONE", "DROPPED"].includes(o.status));
  const closed = objectives.filter((o) => ["DONE", "DROPPED"].includes(o.status));
  const sorted = (rows: Objective[]) =>
    [...rows].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || b.priority - a.priority || b.updated - a.updated);

  const objectiveRow = (o: Objective) => (
    <li key={o.id} className={`mind-obj obj-${o.status.toLowerCase()}`}>
      <div className="mind-obj-main">
        <span className="mind-badge">{o.status}</span>
        <span className="mind-obj-goal">
          #{o.id} · {o.goal}
        </span>
        <span className="mind-obj-meta">
          P{o.priority} · {o.source} · {o.attempts} attempt{o.attempts === 1 ? "" : "s"} · {ago(o.updated)}
        </span>
      </div>
      {o.next_action && <p className="self-dim">next: {o.next_action}</p>}
      <div className="mind-actions">
        {(o.status === "OPEN" || o.status === "ACTIVE" || o.status === "BLOCKED") && (
          <button type="button" className="hud-link" onClick={() => setPending({ id: o.id, status: "DROPPED" })}>
            DROP
          </button>
        )}
        {(o.status === "DONE" || o.status === "BLOCKED" || o.status === "DROPPED") && (
          <button type="button" className="hud-link" onClick={() => setPending({ id: o.id, status: "OPEN" })}>
            REOPEN
          </button>
        )}
      </div>
      {pending?.id === o.id && (
        <div className="brain-inline mind-note">
          <input
            autoFocus
            value={note}
            placeholder={`why ${pending.status === "OPEN" ? "reopen" : "drop"}? (journaled)`}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") decide();
              if (e.key === "Escape") {
                e.stopPropagation();
                setPending(null);
              }
            }}
          />
          <button type="button" className="hud-btn" disabled={!note.trim()} onClick={decide}>
            {pending.status === "OPEN" ? "REOPEN" : "DROP"}
          </button>
          <button type="button" className="hud-link" onClick={() => setPending(null)}>
            CANCEL
          </button>
        </div>
      )}
    </li>
  );

  let body: React.ReactNode;
  if (tab === "briefing") {
    body =
      data.briefing == null ? (
        <div className="brain-empty">Composing from the journal…</div>
      ) : (
        <pre className="mind-briefing">{data.briefing}</pre>
      );
  } else if (tab === "objectives") {
    body =
      data.objectives == null ? (
        <div className="brain-empty">Reading objectives…</div>
      ) : (
        <>
          <div className="brain-inline mind-add">
            <input
              value={goal}
              placeholder="ask SYRAX to learn or do something…"
              onChange={(e) => setGoal(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addObjective()}
            />
            <select value={priority} onChange={(e) => setPriority(Number(e.target.value))} aria-label="priority">
              {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((p) => (
                <option key={p} value={p}>
                  P{p}
                </option>
              ))}
            </select>
            <button type="button" className="hud-btn" disabled={!goal.trim()} onClick={addObjective}>
              ADD
            </button>
          </div>
          <ul className="brain-list mind-list">
            {live.length === 0 && <li className="brain-empty">No open objectives. SYRAX is caught up.</li>}
            {sorted(live).map(objectiveRow)}
            {closed.length > 0 && (
              <li>
                <button type="button" className="hud-link mind-toggle" onClick={() => setShowClosed((v) => !v)}>
                  {showClosed ? "▾" : "▸"} {closed.length} closed (done / dropped)
                </button>
              </li>
            )}
            {showClosed && sorted(closed).map(objectiveRow)}
          </ul>
        </>
      );
  } else if (tab === "proposals") {
    body =
      data.proposals == null ? (
        <div className="brain-empty">Reading proposals…</div>
      ) : data.proposals.length === 0 ? (
        <div className="brain-empty">No proposals yet. They come from SYRAX&rsquo;s research and the radar.</div>
      ) : (
        <ul className="brain-list mind-list">
          {data.proposals.map((p, i) => (
            <li key={`${p.ts}-${i}`} className="mind-card">
              <div className="mind-obj-main">
                <span className="mind-badge">{(p.kind ?? "proposal").toUpperCase()}</span>
                <span className="mind-obj-meta">{ago(p.ts)}</span>
              </div>
              {p.limitation && <p className="self-dim">limitation: {p.limitation}</p>}
              <p>{p.proposal}</p>
              {p.sources && p.sources.length > 0 && (
                <p className="mind-sources">
                  {p.sources.slice(0, 4).map((s) => (
                    <a key={s} href={s} target="_blank" rel="noreferrer">
                      {s.replace(/^https?:\/\//, "").slice(0, 48)}
                    </a>
                  ))}
                </p>
              )}
            </li>
          ))}
        </ul>
      );
  } else if (tab === "skills") {
    body =
      data.skills == null ? (
        <div className="brain-empty">Reading skills…</div>
      ) : data.skills.length === 0 ? (
        <div className="brain-empty">No skills yet. Add an objective and SYRAX will build one.</div>
      ) : (
        <ul className="brain-list mind-list">
          {data.skills.map((s) => (
            <li key={s.name} className={`mind-card skill-${s.status.toLowerCase()}`}>
              <div className="mind-obj-main">
                <span className="mind-badge">{s.status}</span>
                <span className="mind-obj-goal">
                  {s.name} v{s.version}
                </span>
                <span className="mind-obj-meta">
                  {s.tests_passed}✓ {s.tests_failed > 0 ? `${s.tests_failed}✗ ` : ""}· verified {ago(s.last_verified)}
                </span>
              </div>
              <p className="self-dim">{s.purpose}</p>
              {s.real_use && (
                <p className={s.real_use.failures > 0 ? "self-warn" : "self-dim"}>
                  real use: {s.real_use.uses} call{s.real_use.uses === 1 ? "" : "s"}
                  {s.real_use.failures > 0 ? `, ${s.real_use.failures} failed` : ""}
                </p>
              )}
            </li>
          ))}
        </ul>
      );
  } else {
    const rows = Object.entries(data.scorecard ?? {}).sort((a, b) => b[1].tasks - a[1].tasks);
    body =
      data.scorecard == null ? (
        <div className="brain-empty">Scoring brains from the journal…</div>
      ) : rows.length === 0 ? (
        <div className="brain-empty">No brain has answered a task yet.</div>
      ) : (
        <div className="brain-list">
          <p className="self-dim">Each task is credited to the brain that answered most of its steps. Quality comes from graded quality runs.</p>
          {rows.map(([id, c]) => (
            <div key={id} className="mind-score">
              <span className="mind-score-name">{id.toUpperCase()}</span>
              <span className="mind-bar" title={`quality ${pct(c.quality)} over ${c.graded} graded`}>
                <span style={{ width: `${Math.round(c.quality * 100)}%` }} />
              </span>
              <span className="mind-obj-meta">
                quality {pct(c.quality)} ({c.graded} graded) · {c.tasks} tasks · success {pct(c.success_rate)} · {c.avg_steps ?? "—"} steps
              </span>
            </div>
          ))}
        </div>
      );
  }

  return (
    <div className="brain-backdrop" onClick={onClose}>
      <div className="brain-panel self-panel mind-panel" onClick={(e) => e.stopPropagation()}>
        <div className="brain-head">
          <span>// MIND</span>
          <div className="console-tabs" role="tablist">
            {TABS.map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                className="hud-link console-tab"
                onClick={() => onTab(id)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="self-body mind-body">{body}</div>
        <div className="brain-foot">
          <button type="button" className="hud-btn" onClick={refresh}>
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
