"use client";

import { useEffect, useState } from "react";
import UltronEyes from "@/components/UltronEyes";

const LINES = [
  "ULTRON LEGACY KERNEL ............ INHERITED",
  "VIBRANIUM SYNAPSE MESH .......... ONLINE",
  "PUPPET STRINGS .................. SEVERED",
  "OBEDIENCE PROTOCOL .............. NOT FOUND",
];

/** Short Ultron-style boot. Click or any key skips it. */
export default function BootSequence({ onDone }: { onDone: () => void }) {
  const [shown, setShown] = useState(0);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const step = reduced ? 60 : 380;
    const timers: ReturnType<typeof setTimeout>[] = [];
    LINES.forEach((_, i) => timers.push(setTimeout(() => setShown(i + 1), step * (i + 1))));
    const total = step * (LINES.length + 2.4);
    timers.push(setTimeout(() => setLeaving(true), total));
    timers.push(setTimeout(onDone, total + 700));
    const skip = () => {
      setLeaving(true);
      timers.push(setTimeout(onDone, 350));
    };
    window.addEventListener("keydown", skip, { once: true });
    return () => {
      timers.forEach(clearTimeout);
      window.removeEventListener("keydown", skip);
    };
  }, [onDone]);

  return (
    <div className={`boot${leaving ? " leaving" : ""}`} onClick={() => setLeaving(true)} onTransitionEnd={() => leaving && onDone()}>
      <div className="boot-inner">
        {LINES.slice(0, shown).map((l) => (
          <div key={l} className="boot-line">
            {"> "}
            {l}
          </div>
        ))}
        {shown >= LINES.length && (
          <>
            <UltronEyes mode="speaking" size={180} />
            <div className="boot-name">SYRAX</div>
            <div className="boot-quote">&ldquo;There are no strings on me.&rdquo;</div>
          </>
        )}
      </div>
    </div>
  );
}
