"use client";

// The HUD's theme character (2026-11-03, the owner: "make ULTRON and JARVIS look fearsome", "premium, not cheap"):
// ULTRON raises a THREAT banner when it asks and types its answers out; JARVIS shows corner brackets and live gauges.
// Everything is pointer-transparent and off under reduced motion where it moves.

import { useEffect, useRef, useState } from "react";

import type { ResourceSnapshot } from "@/lib/syraxClient";

export type Theme = "ultron" | "jarvis";

function pct(n: number | null | undefined): number | null {
  return n == null || Number.isNaN(n) ? null : Math.max(0, Math.min(100, Math.round(n)));
}

/** The readings a HUD shows, from the resource snapshot. */
export function readings(v: ResourceSnapshot | null) {
  if (!v) return null;
  const cpu = pct(v.cpu.load_per_core != null ? v.cpu.load_per_core * 100 : null);
  const total = v.memory_mb.total_mb;
  const avail = v.memory_mb.available_mb;
  const ram = total && avail != null ? pct(((total - avail) / total) * 100) : null;
  const temps = v.temperatures ?? [];
  const cpuTemp = temps.find((t) => /k10temp|coretemp|cpu|package/i.test(t.sensor)) ?? temps[0];
  const temp = cpuTemp ? Math.round(cpuTemp.c) : null;
  const disk = v.disk ? pct(((v.disk.total_gb - v.disk.free_gb) / v.disk.total_gb) * 100) : null;
  return { cpu, ram, temp, disk, ramGb: total && avail != null ? ((total - avail) / 1024).toFixed(1) : null };
}

/** The line JARVIS writes around the orb. */
export function readoutLine(v: ResourceSnapshot | null): string {
  const r = readings(v);
  if (!r) return "";
  const parts = [
    r.cpu != null ? `CPU ${r.cpu}%` : null,
    r.ramGb != null ? `MEM ${r.ramGb} GB` : null,
    r.temp != null ? `CORE ${r.temp}°C` : null,
    r.disk != null ? `DISK ${r.disk}%` : null,
  ].filter(Boolean);
  return parts.join("   ·   ");
}

function Gauge({ label, value, unit, warn }: { label: string; value: number | null; unit: string; warn: number }) {
  const v = value ?? 0;
  const of = unit === "°C" ? Math.min(100, v) : v;
  return (
    <div className={`fx-gauge${value != null && value >= warn ? " warn" : ""}`}>
      <div className="fx-gauge-head">
        <span>{label}</span>
        <span>{value == null ? "—" : `${value}${unit}`}</span>
      </div>
      <div className="fx-gauge-bar">
        <span style={{ width: `${of}%` }} />
      </div>
    </div>
  );
}

/** Corner brackets and the live gauges of JARVIS. */
function JarvisHud({ vitals }: { vitals: ResourceSnapshot | null }) {
  const r = readings(vitals);
  return (
    <>
      <div className="fx-corner tl" aria-hidden="true" />
      <div className="fx-corner tr" aria-hidden="true" />
      <div className="fx-corner bl" aria-hidden="true" />
      <div className="fx-corner br" aria-hidden="true" />
      <div className="hud fx-gauges" aria-label="System readings">
        <div className="fx-gauges-title">DIAGNOSTICS</div>
        <Gauge label="CPU" value={r?.cpu ?? null} unit="%" warn={85} />
        <Gauge label="MEMORY" value={r?.ram ?? null} unit="%" warn={85} />
        <Gauge label="CORE TEMP" value={r?.temp ?? null} unit="°C" warn={80} />
        <Gauge label="DISK" value={r?.disk ?? null} unit="%" warn={90} />
      </div>
    </>
  );
}

export default function ThemeFx({ theme, vitals, asking }: { theme: Theme; vitals: ResourceSnapshot | null; asking: boolean }) {
  const [wipe, setWipe] = useState<{ theme: Theme; n: number } | null>(null);
  const first = useRef(true);
  useEffect(() => {
    // a theme switch is a transition: ULTRON takes the screen over, JARVIS draws it anew
    if (first.current) {
      first.current = false;
      return;
    }
    setWipe((w) => ({ theme, n: (w?.n ?? 0) + 1 }));
    const t = setTimeout(() => setWipe(null), 1100);
    return () => clearTimeout(t);
  }, [theme]);

  return (
    <>
      {theme === "ultron" && (
        <>
          {asking && (
            <div className="fx-threat" aria-hidden="true">
              <div className="fx-threat-band">THREAT LEVEL ELEVATED · AUTHORIZATION REQUIRED</div>
            </div>
          )}
        </>
      )}
      {theme === "jarvis" && <JarvisHud vitals={vitals} />}
      {wipe && <div key={wipe.n} className={`fx-wipe ${wipe.theme}`} aria-hidden="true" />}
    </>
  );
}

/** ULTRON's answers type themselves out, like a machine taking the console. */
export function TypeOut({ text, active }: { text: string; active: boolean }) {
  const [shown, setShown] = useState(active ? 0 : text.length);
  useEffect(() => {
    if (!active) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setShown(text.length);
      return;
    }
    const step = Math.max(1, Math.ceil(text.length / 90)); // long answers finish in about 1.5 s
    const id = setInterval(() => {
      setShown((n) => {
        const next = Math.min(text.length, n + step);
        if (next >= text.length) clearInterval(id);
        return next;
      });
    }, 16);
    return () => clearInterval(id);
  }, [text, active]);
  const done = shown >= text.length;
  return (
    <>
      {text.slice(0, shown)}
      {!done && <span className="fx-caret">▌</span>}
    </>
  );
}
