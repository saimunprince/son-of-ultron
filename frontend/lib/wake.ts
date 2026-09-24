/* Decide what a heard utterance means. Pure and dependency-free so it can be
 * tested without a browser. */

export type Heard =
  | { kind: "ignore"; reason: "empty" | "not-addressed" | "echo" }
  | { kind: "abort" } // stop the running task and the voice
  | { kind: "silence" } // just stop talking
  | { kind: "wake" } // "SYRAX" alone: open the follow-up window
  | { kind: "command"; text: string };

export interface HeardContext {
  /** true inside the follow-up window or while SYRAX waits for an answer */
  armed: boolean;
  /** true while SYRAX's voice is playing */
  speaking: boolean;
  /** what SYRAX is currently saying (for echo rejection) */
  spokenText?: string;
  /** a task is running: bare "stop" aborts it, other chatter is ignored */
  busy?: boolean;
}

// Whisper spells the name many ways; accept the usual suspects.
const WAKE = /\b(?:hey|hi|ok|okay|yo|oi)?[\s,]*(?:syrax|sy\s?rax|sirax|siraks|syracks|cyrax|cirax|sairax|sai\s?rax|syrex|sirex|syrix|zyrax|sy-rax|saraks|serax|sorax)\b[\s,.!?:;-]*/i;
// Bengali-script recognisers (Chrome bn-BD) spell the name like this.
const WAKE_BN = /(?:হেই|হে|ওকে)?\s*(?:সাইরাক্স|সাইরেক্স|সিরাক্স|সিরেক্স|সায়রাক্স|সাইর্যাক্স|সাইরাক্‌স|সাইরাস)[\s,.!?।:;-]*/u;
const ABORT = /^(?:please\s+)?(?:stop|abort|cancel|halt|terminate|kill it|stop it|stop that|enough|thamo|tham|bondho koro|থামো|থাম|স্টপ|বন্ধ কর)/iu;
const SILENCE = /^(?:shut up|be quiet|quiet|silence|mute|hush|stop talking|chup|chup koro|চুপ)/iu;

function normalize(s: string) {
  return s.toLowerCase().replace(/[^\p{L}\p{N}\s'-]/gu, " ").replace(/\s+/g, " ").trim();
}

function overlap(heard: string, spoken: string) {
  const h = normalize(heard).split(" ").filter((w) => w.length > 2);
  if (h.length === 0) return 0;
  const s = new Set(normalize(spoken).split(" "));
  return h.filter((w) => s.has(w)).length / h.length;
}

export function interpret(raw: string, ctx: HeardContext): Heard {
  const text = raw.trim();
  if (!normalize(text)) return { kind: "ignore", reason: "empty" };

  const wake = WAKE.exec(text) ?? WAKE_BN.exec(text);
  const rest = wake ? (text.slice(0, wake.index) + " " + text.slice(wake.index + wake[0].length)).trim() : text;
  const restClean = rest.replace(/^[\s,.!?:;-]+/, "");

  // Control words work with or without the name, but only when addressed,
  // armed, or while SYRAX is talking (barge-in).
  const addressed = !!wake || ctx.armed || ctx.speaking || !!ctx.busy;
  if (addressed && ABORT.test(restClean)) return { kind: "abort" };
  if (addressed && SILENCE.test(restClean)) return { kind: "silence" };

  if (ctx.speaking && !wake) {
    // Anything else heard while SYRAX talks is most likely its own voice.
    return { kind: "ignore", reason: "echo" };
  }
  if (ctx.speaking && ctx.spokenText && overlap(text, ctx.spokenText) > 0.6) {
    return { kind: "ignore", reason: "echo" };
  }

  if (ctx.busy && !wake) return { kind: "ignore", reason: "not-addressed" };
  if (wake) {
    return restClean.length >= 2 ? { kind: "command", text: restClean } : { kind: "wake" };
  }
  if (ctx.armed) return { kind: "command", text };
  return { kind: "ignore", reason: "not-addressed" };
}
