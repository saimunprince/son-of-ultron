// The operator's autonomy level in the HUD (backend permissions.LEVEL_NAMES, WS "autonomy_level"). Pure for node --test.
import type { AutonomyStatus } from "./syraxClient";

export const LEVEL_NAMES: Record<number, string> = {
  1: "observe and research",
  2: "experiment",
  3: "modify and verify",
  4: "integrate",
  5: "continuous",
};

export function levelOf(a: AutonomyStatus | null | undefined): number {
  const l = a?.level ?? 5;
  return Math.max(1, Math.min(5, Math.round(l)));
}

export function levelTitle(a: AutonomyStatus | null | undefined): string {
  const l = levelOf(a);
  return `Autonomy level ${l} (${LEVEL_NAMES[l]}): how far SYRAX's own work may go. Only you change it.`;
}

/** One step down (-1) or up (+1), never past 1..5. */
export function levelStep(a: AutonomyStatus | null | undefined, step: -1 | 1): { type: "autonomy_level"; level: number } {
  return { type: "autonomy_level", level: Math.max(1, Math.min(5, levelOf(a) + step)) };
}
