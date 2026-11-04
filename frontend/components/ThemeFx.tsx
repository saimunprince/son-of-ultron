"use client";

// The HUD's diagnostics (2026-11-03): corner brackets and live gauges. Since 2026-11-04 both themes share the JARVIS
// design ("the red UI is JARVIS's UI in red"); only the colour differs.
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

export default function ThemeFx({ theme, vitals }: { theme: Theme; vitals: ResourceSnapshot | null }) {
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
      <JarvisHud vitals={vitals} />
      {wipe && <div key={wipe.n} className="fx-wipe" aria-hidden="true" />}
    </>
  );
}
