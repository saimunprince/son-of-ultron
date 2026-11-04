"use client";

// A crash in one optional part of the HUD (chip, arc, caption, toasts, palette, effects) hides that part only.
// Live 2026-11-04: a brain event without a provider made the brain chip throw, and the whole page went blank.

import { Component, type ReactNode } from "react";

export default class Guard extends Component<{ name: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: unknown): void {
    console.warn(`SYRAX: the ${this.props.name} stopped after an error; the rest of the HUD keeps running.`, error);
  }

  render(): ReactNode {
    return this.state.failed ? null : this.props.children;
  }
}
