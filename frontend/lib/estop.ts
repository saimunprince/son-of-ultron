// The operator's emergency stop in the HUD (backend syrax/estop.py, WS "estop"). Pure, so node --test can check it.
import type { AutonomyStatus } from "./syraxClient";

export function estopOn(a: AutonomyStatus | null | undefined): boolean {
  return !!a?.estop;
}

/** The button's label: what pressing it does next. */
export function estopLabel(a: AutonomyStatus | null | undefined): string {
  return estopOn(a) ? "E-STOP ON · CLEAR" : "E-STOP";
}

export function estopTitle(a: AutonomyStatus | null | undefined): string {
  if (!estopOn(a)) {
    return "Emergency stop: cancel what runs now and start no work of SYRAX's own (survives restarts) until you clear it";
  }
  const at = a?.estop?.at ? new Date(a.estop.at * 1000).toLocaleString() : "unknown time";
  return `Stopped since ${at}${a?.estop?.note ? `: ${a.estop.note}` : ""}. Click to clear (autonomy stays as it was set).`;
}

/** The message a press sends: on when it is off, off when it is on. */
export function estopMessage(a: AutonomyStatus | null | undefined): { type: "estop"; on: boolean; note?: string } {
  return estopOn(a) ? { type: "estop", on: false, note: "cleared from the HUD" } : { type: "estop", on: true, note: "pressed in the HUD" };
}
