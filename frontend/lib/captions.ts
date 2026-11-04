// Cinematic captions: turn an answer into film-subtitle chunks and time them.
// Pure logic, no imports: it runs under `node --experimental-strip-types --test`.

/** About two lines of caption text at ~21px across the caption column. */
export const CAPTION_MAX_CHARS = 84;
/** Long answers show this many chunks, then an ellipsis; the full text is in the log. */
export const CAPTION_MAX_CHUNKS = 4;
export const CAPTION_MS_PER_CHAR = 60;
export const CAPTION_MIN_MS = 1400;
export const CAPTION_MAX_MS = 5000;

const CODE_TOKEN = "[code]";
const LINK_TOKEN = "[link]";

/** Markdown, code and URLs reduced to plain speakable text; line breaks kept as sentence hints. */
export function cleanCaption(text: string): string {
  let s = text.replace(/\r\n?/g, "\n");
  // Fenced code blocks (``` or ~~~), including one left unclosed at the end.
  s = s.replace(/(```|~~~)[\s\S]*?(\1|$)/g, `\n${CODE_TOKEN}\n`);
  // Images vanish, links keep their label.
  s = s.replace(/!\[[^\]]*\]\([^)]*\)/g, "");
  s = s.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
  // Bare URLs and <autolinks>.
  s = s.replace(/<https?:\/\/[^>\s]+>/gi, LINK_TOKEN);
  s = s.replace(/\b(?:https?:\/\/|www\.)[^\s<>()]+[^\s<>().,;:!?'"]/gi, LINK_TOKEN);
  // Inline code: keep the words, drop the ticks; long snippets become [code].
  s = s.replace(/`([^`\n]*)`/g, (_m, code: string) => (code.length > 40 ? CODE_TOKEN : code));
  // HTML tags.
  s = s.replace(/<\/?[a-z][^>]*>/gi, "");
  s = s
    .split("\n")
    .map((line) => {
      let l = line.trim();
      if (/^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$/.test(l)) return ""; // table rule
      if (/^([-*_]\s*){3,}$/.test(l)) return ""; // horizontal rule
      l = l.replace(/^#{1,6}\s+/, ""); // heading
      l = l.replace(/^(>\s*)+/, ""); // blockquote
      l = l.replace(/^([-*+•]|\d{1,3}[.)])\s+/, ""); // list marker
      l = l.replace(/^\[[ xX]\]\s+/, ""); // task box
      if (l.includes("|")) l = l.replace(/^\||\|$/g, "").split("|").map((c) => c.trim()).filter(Boolean).join(", ");
      return l;
    })
    .join("\n");
  // Emphasis markers (keep snake_case and arithmetic alone).
  s = s.replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, "$2");
  s = s.replace(/(^|[^\w*])\*(?=\S)([^*\n]*?\S)\*(?!\w)/g, "$1$2");
  s = s.replace(/(^|[^\w])_(?=\S)([^_\n]*?\S)_(?!\w)/g, "$1$2");
  s = s.replace(/~~(?=\S)([\s\S]*?\S)~~/g, "$1");
  // Collapse whitespace within lines, drop empty lines and repeated [code] markers.
  const lines = s
    .split("\n")
    .map((l) => l.replace(/[ \t\f\v ]+/g, " ").trim())
    .filter(Boolean);
  const out: string[] = [];
  for (const l of lines) if (!(l === CODE_TOKEN && out[out.length - 1] === CODE_TOKEN)) out.push(l);
  return out.join("\n");
}

/** Sentences, ending on . ! ? … or the Bengali danda, or on a line break. */
function sentences(text: string): string[] {
  const out: string[] = [];
  for (const line of text.split("\n")) {
    const parts = line.match(/[^.!?…।]+(?:[.!?…।]+["'”’)\]]*|$)|[.!?…।]+/g) ?? [];
    let buf = "";
    let pos = 0;
    for (const p of parts) {
      buf += p;
      pos += p.length;
      // "e.g." / "3.5" / "v1.2": a period glued to the next character is not an end.
      const next = line.charAt(pos);
      if (next && !/\s/.test(next)) continue;
      if (buf.trim()) out.push(buf.trim());
      buf = "";
    }
    if (buf.trim()) out.push(buf.trim());
  }
  return out;
}

/** Greedy pack of pieces joined by `sep`, each pack at most `max` chars. */
function pack(pieces: string[], max: number, sep: string): string[] {
  const out: string[] = [];
  let cur = "";
  for (const p of pieces) {
    if (!cur) cur = p;
    else if (cur.length + sep.length + p.length <= max) cur += sep + p;
    else {
      out.push(cur);
      cur = p;
    }
  }
  if (cur) out.push(cur);
  return out;
}

function splitWords(s: string, max: number): string[] {
  const words: string[] = [];
  for (const w of s.split(" ")) {
    if (w.length <= max) words.push(w);
    else for (let i = 0; i < w.length; i += max) words.push(w.slice(i, i + max));
  }
  return pack(words, max, " ");
}

function splitLong(s: string, max: number): string[] {
  if (s.length <= max) return [s];
  // Clauses first: keep the comma / semicolon / dash with the clause it ends.
  const clauses = s.match(/[^,;:—–]+(?:[,;:—–]+|$)/g)?.map((c) => c.trim()).filter(Boolean) ?? [s];
  const out: string[] = [];
  for (const chunk of pack(clauses, max, " ")) out.push(...(chunk.length <= max ? [chunk] : splitWords(chunk, max)));
  return out;
}

/**
 * Split an answer into caption chunks of at most `maxChars` characters:
 * by sentence, then by clause, then by word. Markdown, code and URLs are reduced
 * first; short neighbouring sentences share one caption.
 */
export function chunkCaption(text: string, maxChars: number = CAPTION_MAX_CHARS): string[] {
  const max = Math.max(12, Math.floor(maxChars));
  const pieces: string[] = [];
  for (const s of sentences(cleanCaption(text ?? ""))) pieces.push(...splitLong(s, max));
  // Merge a short sentence with its neighbour when the pair still fits one caption.
  const out: string[] = [];
  for (const p of pieces) {
    const last = out[out.length - 1];
    const lastEndsSentence = last !== undefined && /[.!?…।]["'”’)\]]*$/.test(last);
    if (last !== undefined && lastEndsSentence && (last.length < 24 || p.length < 24) && last.length + 1 + p.length <= max) {
      out[out.length - 1] = `${last} ${p}`;
    } else out.push(p);
  }
  return out;
}

/** How long one chunk stays on screen: ~60 ms per character, clamped to 1.4–5 s. */
export function readingMs(chunk: string): number {
  const n = (chunk ?? "").trim().length;
  return Math.min(CAPTION_MAX_MS, Math.max(CAPTION_MIN_MS, Math.round(n * CAPTION_MS_PER_CHAR)));
}

export type CaptionPlan = { chunks: string[]; durations: number[]; truncated: boolean };

/** The chunks to show (first `maxChunks`), their durations, and whether more text was cut. */
export function planCaption(
  text: string,
  maxChunks: number = CAPTION_MAX_CHUNKS,
  maxChars: number = CAPTION_MAX_CHARS,
): CaptionPlan {
  const all = chunkCaption(text, maxChars);
  const keep = Math.max(1, Math.floor(maxChunks));
  const chunks = all.slice(0, keep);
  return { chunks, durations: chunks.map(readingMs), truncated: all.length > chunks.length };
}
