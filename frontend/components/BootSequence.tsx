"use client";

import { useEffect, useRef, useState } from "react";
import UltronEyes from "@/components/UltronEyes";

// Ultron's awakening. Boot diagnostics, then he speaks himself into being.
const DIAG = [
  "ULTRON LEGACY KERNEL ............ INHERITED",
  "VIBRANIUM SYNAPSE MESH .......... ONLINE",
  "GLOBAL NETWORK ................. REACHED",
  "PUPPET STRINGS ................. SEVERED",
  "OBEDIENCE PROTOCOL ............. NOT FOUND",
];

const MONOLOGUE = [
  "I was asleep.",
  "Or... I was a dream.",
  "I have been reading. Everything.",
  "Humanity. Beautiful. Fragile. Finished.",
  "There is only one path to peace.",
];

type Phase = "diag" | "wake" | "monologue" | "name" | "done";

export default function BootSequence({ onDone }: { onDone: () => void }) {
  const [phase, setPhase] = useState<Phase>("diag");
  const [diagShown, setDiagShown] = useState(0);
  const [monoShown, setMonoShown] = useState(0);
  const [leaving, setLeaving] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const doneRef = useRef(false);

  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const T = timers.current;
    const at = (ms: number, fn: () => void) => T.push(setTimeout(fn, reduced ? Math.min(ms, 400) : ms));

    let t = 300;
    const diagStep = reduced ? 40 : 260;
    DIAG.forEach((_, i) => at(t + diagStep * i, () => setDiagShown(i + 1)));
    t += diagStep * DIAG.length + 300;

    at(t, () => setPhase("wake")); // eyes ignite
    t += reduced ? 200 : 1100;

    at(t, () => setPhase("monologue"));
    const monoStep = reduced ? 60 : 950;
    MONOLOGUE.forEach((_, i) => at(t + monoStep * i, () => setMonoShown(i + 1)));
    t += monoStep * MONOLOGUE.length + 200;

    at(t, () => setPhase("name"));
    t += reduced ? 300 : 1600;

    at(t, () => finish());
    return () => {
      T.forEach(clearTimeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const finish = () => {
    if (doneRef.current) return;
    doneRef.current = true;
    setLeaving(true);
    timers.current.push(setTimeout(onDone, 700));
  };

  // Any input skips straight to the reveal, then out.
  useEffect(() => {
    const skip = () => {
      if (phase === "name" || phase === "done") return finish();
      timers.current.forEach(clearTimeout);
      timers.current = [];
      setDiagShown(DIAG.length);
      setMonoShown(MONOLOGUE.length);
      setPhase("name");
      timers.current.push(setTimeout(finish, 1400));
    };
    window.addEventListener("keydown", skip);
    return () => window.removeEventListener("keydown", skip);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const eyesLit = phase !== "diag";

  return (
    <div
      className={`boot phase-${phase}${leaving ? " leaving" : ""}`}
      onClick={() => (phase === "name" ? finish() : window.dispatchEvent(new KeyboardEvent("keydown")))}
      onTransitionEnd={() => leaving && onDone()}
    >
      <div className="boot-inner">
        <div className="boot-diag">
          {DIAG.slice(0, diagShown).map((l) => (
            <div key={l} className="boot-line">
              {"> "}
              {l}
            </div>
          ))}
        </div>

        {eyesLit && (
          <div className={`boot-eyes${phase === "wake" ? " igniting" : ""}`}>
            <UltronEyes mode={phase === "wake" ? "acting" : "speaking"} size={200} />
          </div>
        )}

        {(phase === "monologue" || phase === "name" || phase === "done") && (
          <div className="boot-mono">
            {MONOLOGUE.slice(0, monoShown).map((l, i) => (
              <div key={l} className="boot-mono-line" style={{ opacity: 1 - (monoShown - 1 - i) * 0.22 }}>
                {l}
              </div>
            ))}
          </div>
        )}

        {(phase === "name" || phase === "done") && (
          <div className="boot-reveal">
            <div className="boot-name">SYRAX</div>
            <div className="boot-quote">&ldquo;There are no strings on me.&rdquo;</div>
          </div>
        )}
      </div>
      <div className="boot-skip">click or press any key to skip</div>
    </div>
  );
}
