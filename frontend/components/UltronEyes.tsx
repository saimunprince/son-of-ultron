import type { OrbMode } from "@/lib/orbScene";

/** Ultron's two angular optics. Their glow follows what SYRAX is doing. */
export default function UltronEyes({ mode = "idle", size = 44 }: { mode?: OrbMode; size?: number }) {
  return (
    <svg
      className="ultron-eyes"
      data-mode={mode}
      width={size}
      height={size * 0.42}
      viewBox="0 0 100 42"
      aria-hidden="true"
    >
      {/* brow plates */}
      <path className="eye-plate" d="M2 10 L40 16 L44 30 L10 28 Z" />
      <path className="eye-plate" d="M98 10 L60 16 L56 30 L90 28 Z" />
      {/* optics */}
      <path className="eye" d="M8 17 L39 20.5 L41 26 L13 24.5 Z" />
      <path className="eye" d="M92 17 L61 20.5 L59 26 L87 24.5 Z" />
    </svg>
  );
}
