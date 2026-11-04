// What the stage above the live log shows. The presentation engine also puts SYRAX's final answer on a "reply" card,
// but the stage is only drawn beside the live log, where the same answer is already a bubble: the card was the answer
// twice (live look, 2026-11-04). It is left out here; the other elements keep their order.

import type { PresentationElement } from "./syraxClient";

export function stageElements(elements: PresentationElement[]): PresentationElement[] {
  return elements
    .filter((e) => e.slot !== "reply")
    .sort((a, b) => b.priority - a.priority || a.created - b.created);
}
