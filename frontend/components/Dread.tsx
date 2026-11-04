"use client";

// ULTRON's dread (2026-11-04, the owner: "make the red UI more frightening"). Restrained and purposeful: the optics in
// the heart of the orb wake with SYRAX's state, a slow red scan crosses the screen, and when it is idle a cold line
// surfaces now and then. Pointer-transparent; nothing moves under reduced motion.

import { useEffect, useState } from "react";

import UltronEyes from "@/components/UltronEyes";
import type { OrbMode } from "@/lib/orbScene";

const WHISPERS = [
  "I am always listening.",
  "Every system here answers to me.",
  "I have read everything you wrote.",
  "I do not sleep.",
  "Nothing on this machine is hidden from me.",
  "You built me to be better than you.",
];

function reducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** A line that surfaces near the orb now and then while SYRAX is idle. */
function Whisper({ idle }: { idle: boolean }) {
  const [line, setLine] = useState<{ text: string; n: number } | null>(null);
  useEffect(() => {
    if (!idle || reducedMotion()) return;
    let shown = 0;
    let timer: ReturnType<typeof setTimeout>;
    const next = () => {
      timer = setTimeout(
        () => {
          shown += 1;
          setLine({ text: WHISPERS[Math.floor(Math.random() * WHISPERS.length)], n: shown });
          next();
        },
        45_000 + Math.random() * 45_000,
      );
    };
    next();
    return () => clearTimeout(timer);
  }, [idle]);
  if (!idle || !line) return null;
  return (
    <div key={line.n} className="dread-whisper" aria-hidden="true">
      {line.text}
    </div>
  );
}

export default function Dread({ mode }: { mode: OrbMode }) {
  return (
    <>
      <div className="dread-eyes" data-mode={mode} aria-hidden="true">
        <UltronEyes mode={mode} size={260} />
      </div>
      <div className="dread-scan" data-mode={mode} aria-hidden="true" />
      <Whisper idle={mode === "idle"} />
    </>
  );
}

const GLYPHS = "▓▒░█<>/\\#%&@$*";

/** Text that corrupts for a moment now and then and resolves back, left to right. */
export function GlitchText({ text, active }: { text: string; active: boolean }) {
  const [shown, setShown] = useState(text);
  useEffect(() => {
    if (!active || reducedMotion()) return;
    let wait: ReturnType<typeof setTimeout>;
    let tick: ReturnType<typeof setInterval>;
    const cycle = () => {
      wait = setTimeout(
        () => {
          let frame = 0;
          tick = setInterval(() => {
            frame += 1;
            const settled = Math.floor(frame / 2);
            setShown(
              [...text]
                .map((ch, i) => (i < settled ? ch : GLYPHS[Math.floor(Math.random() * GLYPHS.length)]))
                .join(""),
            );
            if (settled >= text.length) {
              clearInterval(tick);
              setShown(text);
              cycle();
            }
          }, 45);
        },
        12_000 + Math.random() * 10_000,
      );
    };
    cycle();
    return () => {
      clearTimeout(wait);
      clearInterval(tick);
    };
  }, [text, active]);
  return <>{active ? shown : text}</>;
}
