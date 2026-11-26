/* Push-to-talk keys (2026-11-26): hold a key to listen, release to send.
 * Keys are KeyboardEvent.code values, so the layout does not matter. */

export interface TargetLike {
  tagName?: string;
  isContentEditable?: boolean;
  type?: string;
  getAttribute?: (name: string) => string | null;
}

const TEXT_INPUT_TYPES = new Set(["checkbox", "radio", "button", "submit", "reset", "range", "color", "file", "image"]);

/** Focus is in something that takes typing: a text input, a textarea, a select or an editable element. */
export function isTypingElement(t: TargetLike | null | undefined): boolean {
  if (!t) return false;
  const tag = (t.tagName ?? "").toUpperCase();
  if (t.isContentEditable || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") return !TEXT_INPUT_TYPES.has((t.type ?? "text").toLowerCase());
  return false;
}

/** Focus is on a control that Space or Enter already activates (a button, a link, a checkbox). */
export function isActivatable(t: TargetLike | null | undefined): boolean {
  if (!t) return false;
  const tag = (t.tagName ?? "").toUpperCase();
  if (tag === "BUTTON" || tag === "A" || tag === "SUMMARY" || tag === "INPUT") return true;
  const role = t.getAttribute?.("role");
  return role === "button" || role === "switch" || role === "checkbox" || role === "tab" || role === "option";
}

/** The HUD's own single-key shortcuts and keys the page needs: never a push-to-talk key. */
const RESERVED = new Set([
  "KeyM", "KeyB", "KeyS", "KeyO", "KeyC", "KeyG", "KeyR", "KeyK",
  "Slash", "Equal", "Minus", "NumpadAdd", "NumpadSubtract",
  "Escape", "Enter", "NumpadEnter", "Tab", "Backspace",
  "ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight", "AltLeft", "AltRight", "MetaLeft", "MetaRight", "CapsLock",
]);

export function pttKeyAllowed(code: string): boolean {
  return !!code && !RESERVED.has(code);
}

/** A short name for the key: "SPACE", "T", "1", "F2", "`". */
export function keyLabel(code: string): string {
  if (code === "Space") return "SPACE";
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit\d$/.test(code)) return code.slice(5);
  if (/^Numpad\d$/.test(code)) return `NUM ${code.slice(6)}`;
  const named: Record<string, string> = { Backquote: "`", Backslash: "\\", Quote: "'", Semicolon: ";", Comma: ",", Period: "." };
  return named[code] ?? code.toUpperCase();
}

export interface KeyLike {
  code: string;
  repeat?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  /** a DOM EventTarget in the page; only its tag, type, role and editability are read */
  target?: TargetLike | EventTarget | null;
}

/** This keydown starts push-to-talk: the chosen key, no modifier, no auto-repeat, focus not in a text field,
 *  and for Space/Enter not on a control those keys already press (keyboard users keep their buttons). */
export function pttStarts(e: KeyLike, pttKey: string): boolean {
  if (e.code !== pttKey || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return false;
  const target = e.target as TargetLike | null | undefined;
  if (isTypingElement(target)) return false;
  if ((pttKey === "Space" || pttKey === "Enter") && isActivatable(target)) return false;
  return true;
}
