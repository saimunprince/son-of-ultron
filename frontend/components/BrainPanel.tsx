"use client";

import { useEffect, useMemo, useState } from "react";
import type { BrainChange, BrainProvider, BrainsState, BrainTestResult } from "@/lib/syraxClient";

interface Props {
  state: BrainsState | null;
  models: Record<string, { list: string[]; error?: string; loading: boolean }>;
  tests: Record<string, BrainTestResult | "running">;
  onSave: (changes: Record<string, BrainChange>, order: string[]) => void;
  onModels: (id: string, apiKey?: string) => void;
  onTest: (id: string) => void;
  onClose: () => void;
}

const TIER_LABEL: Record<BrainProvider["tier"], string> = {
  "no-key": "FREE · NO KEY",
  local: "FREE · LOCAL",
  free: "FREE TIER",
  paid: "PAID",
};

const STATUS_LABEL: Record<BrainProvider["status"], string> = {
  ready: "READY",
  cooldown: "COOLING",
  "no-key": "NEEDS KEY",
  off: "OFF",
};

export default function BrainPanel({ state, models, tests, onSave, onModels, onTest, onClose }: Props) {
  const [order, setOrder] = useState<string[]>([]);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [modelDraft, setModelDraft] = useState<Record<string, string>>({});
  const [enabledDraft, setEnabledDraft] = useState<Record<string, boolean>>({});
  const [open, setOpen] = useState<string | null>(null);

  const byId = useMemo(() => {
    const m: Record<string, BrainProvider> = {};
    state?.providers.forEach((p) => (m[p.id] = p));
    return m;
  }, [state]);

  // Adopt server order when it changes (e.g. after a save)
  useEffect(() => {
    if (state) setOrder(state.order);
  }, [state]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const dirty =
    Object.values(keys).some((v) => v.trim()) ||
    Object.keys(modelDraft).length > 0 ||
    Object.keys(enabledDraft).length > 0 ||
    (state && order.join() !== state.order.join());

  const move = (id: string, dir: -1 | 1) => {
    setOrder((prev) => {
      const i = prev.indexOf(id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const save = () => {
    const changes: Record<string, BrainChange> = {};
    for (const [id, v] of Object.entries(keys)) if (v.trim()) (changes[id] ??= {}).api_key = v.trim();
    for (const [id, v] of Object.entries(modelDraft)) (changes[id] ??= {}).model = v.trim();
    for (const [id, v] of Object.entries(enabledDraft)) (changes[id] ??= {}).enabled = v;
    onSave(changes, order);
    setKeys({});
    setModelDraft({});
    setEnabledDraft({});
  };

  const removeKey = (id: string) => onSave({ [id]: { api_key: "" } }, order);

  if (!state) {
    return (
      <div className="brain-backdrop" onClick={onClose}>
        <div className="brain-panel" onClick={(e) => e.stopPropagation()}>
          <div className="brain-head">
            <span>// BRAIN MATRIX</span>
          </div>
          <div className="brain-empty">No link to the core.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="brain-backdrop" onClick={onClose}>
      <div className="brain-panel" role="dialog" aria-label="Brain settings" onClick={(e) => e.stopPropagation()}>
        <div className="brain-head">
          <span>// BRAIN MATRIX</span>
          <button type="button" className="hud-link" onClick={onClose}>
            CLOSE
          </button>
        </div>
        <p className="brain-intro">
          SYRAX tries brains top to bottom and fails over on limits or errors. Keys stay on this machine in
          backend/config/brains.json.
        </p>

        <ol className="brain-list">
          {order.map((id, idx) => {
            const p = byId[id];
            if (!p) return null;
            const enabled = enabledDraft[id] ?? p.enabled;
            const test = tests[id];
            const m = models[id];
            const listId = `models-${id}`;
            const expanded = open === id;
            return (
              <li key={id} className={`brain-row status-${p.status}${state.active === id ? " active" : ""}`}>
                <div className="brain-row-main">
                  <span className="brain-rank">{String(idx + 1).padStart(2, "0")}</span>
                  <button type="button" className="brain-name" onClick={() => setOpen(expanded ? null : id)} aria-expanded={expanded}>
                    {p.label}
                    <span className={`brain-tier tier-${p.tier}`}>{TIER_LABEL[p.tier]}</span>
                  </button>
                  <span className="brain-status" title={p.reason || undefined}>
                    {state.active === id ? "ACTIVE" : STATUS_LABEL[p.status]}
                    {p.status === "cooldown" && p.cooldown_s > 0 ? ` ${p.cooldown_s}s` : ""}
                  </span>
                  <label className="brain-toggle" title="Use this brain">
                    <input
                      type="checkbox"
                      checked={enabled}
                      disabled={p.key_required && !p.has_key && !keys[id]?.trim()}
                      onChange={(e) => setEnabledDraft((d) => ({ ...d, [id]: e.target.checked }))}
                    />
                    <span />
                  </label>
                  <div className="brain-move">
                    <button type="button" className="hud-link" onClick={() => move(id, -1)} disabled={idx === 0} aria-label="Move up">
                      ▲
                    </button>
                    <button type="button" className="hud-link" onClick={() => move(id, 1)} disabled={idx === order.length - 1} aria-label="Move down">
                      ▼
                    </button>
                  </div>
                </div>

                {expanded && (
                  <div className="brain-detail">
                    <div className="brain-note">{p.note}</div>
                    {(p.key_required || p.id === "pollinations") && (
                      <div className="brain-field">
                        <label htmlFor={`key-${id}`}>{p.key_required ? "API KEY" : "TOKEN (OPTIONAL)"}</label>
                        <div className="brain-inline">
                          <input
                            id={`key-${id}`}
                            type="password"
                            autoComplete="off"
                            spellCheck={false}
                            placeholder={p.has_key ? `saved ${p.key_hint}` : "paste key"}
                            value={keys[id] ?? ""}
                            onChange={(e) => setKeys((k) => ({ ...k, [id]: e.target.value }))}
                          />
                          {p.has_key && (
                            <button type="button" className="hud-link" onClick={() => removeKey(id)}>
                              REMOVE
                            </button>
                          )}
                          {p.signup_url && (
                            <a className="hud-link" href={p.signup_url} target="_blank" rel="noreferrer">
                              GET KEY ↗
                            </a>
                          )}
                        </div>
                      </div>
                    )}
                    {!p.key_required && p.id === "ollama" && p.signup_url && (
                      <a className="hud-link" href={p.signup_url} target="_blank" rel="noreferrer">
                        INSTALL OLLAMA ↗
                      </a>
                    )}
                    <div className="brain-field">
                      <label htmlFor={`model-${id}`}>MODEL</label>
                      <div className="brain-inline">
                        <input
                          id={`model-${id}`}
                          list={listId}
                          spellCheck={false}
                          value={modelDraft[id] ?? p.model}
                          placeholder="choose a model"
                          onChange={(e) => setModelDraft((d) => ({ ...d, [id]: e.target.value }))}
                        />
                        <datalist id={listId}>
                          {(m?.list ?? []).map((x) => (
                            <option key={x} value={x} />
                          ))}
                        </datalist>
                        <button
                          type="button"
                          className="hud-link"
                          onClick={() => onModels(id, keys[id]?.trim() || undefined)}
                          disabled={m?.loading}
                        >
                          {m?.loading ? "LOADING…" : m?.list?.length ? `${m.list.length} MODELS` : "LOAD MODELS"}
                        </button>
                      </div>
                      {m?.error && <div className="brain-error">{m.error}</div>}
                    </div>
                    <div className="brain-inline">
                      <button
                        type="button"
                        className="hud-btn"
                        onClick={() => onTest(id)}
                        disabled={test === "running" || dirty === true}
                        title={dirty ? "Save first" : "Send a tiny tool-call test"}
                      >
                        {test === "running" ? "TESTING…" : "TEST"}
                      </button>
                      {test && test !== "running" && (
                        <span className={test.ok ? "brain-ok" : "brain-error"}>
                          {test.ok
                            ? `OK · ${test.latency_ms}ms · ${test.tools ? "TOOLS ✓" : "NO TOOL CALL"}`
                            : `FAIL · ${test.error}`}
                        </span>
                      )}
                    </div>
                    {p.reason && p.status === "cooldown" && <div className="brain-error">LAST FAULT · {p.reason}</div>}
                  </div>
                )}
              </li>
            );
          })}
        </ol>

        <div className="brain-foot">
          <button type="button" className="hud-btn" onClick={save} disabled={!dirty}>
            SAVE
          </button>
        </div>
      </div>
    </div>
  );
}
