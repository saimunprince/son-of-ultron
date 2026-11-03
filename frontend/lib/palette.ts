/**
 * Command palette logic: fuzzy scoring, filtering, row layout and keyboard
 * wrap-around. Pure and framework-free so `node --test` can run it directly.
 */

export type PaletteCommand = {
  id: string;
  label: string;
  section: string;
  hint?: string;
  keywords?: string[];
  danger?: boolean;
  disabled?: boolean;
};

/** One rendered line of the palette. `ask` is the free-text fallback. */
export type PaletteRow =
  | { kind: "header"; section: string }
  | { kind: "cmd"; cmd: PaletteCommand; match: number[] }
  | { kind: "ask"; query: string };

/** The id prefix the free-text fallback runs with: `ask:<query>`. */
export const ASK_PREFIX = "ask:";

const norm = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");

function isWordStart(t: string, i: number): boolean {
  if (i === 0) return true;
  const prev = t[i - 1];
  return !/[a-z0-9]/.test(prev);
}

/** Where `q` (already normalized, no spaces) hits `t` (normalized): a contiguous run if
 *  there is one (a word-start run preferred), else a greedy subsequence. null = no match. */
function positions(q: string, t: string): number[] | null {
  if (!q) return [];
  let at = -1;
  for (let i = t.indexOf(q); i !== -1; i = t.indexOf(q, i + 1)) {
    if (at === -1) at = i;
    if (isWordStart(t, i)) {
      at = i;
      break;
    }
  }
  if (at !== -1) return Array.from({ length: q.length }, (_, k) => at + k);
  const out: number[] = [];
  let from = 0;
  for (const ch of q) {
    // prefer a word-start occurrence of this char if one exists before the next plain one would end the match
    let i = t.indexOf(ch, from);
    if (i === -1) return null;
    for (let j = i; j !== -1; j = t.indexOf(ch, j + 1)) {
      if (isWordStart(t, j)) {
        // only jump ahead if the rest of the query still fits after it
        if (fits(q.slice(out.length + 1), t, j + 1)) i = j;
        break;
      }
    }
    out.push(i);
    from = i + 1;
  }
  return out;
}

function fits(rest: string, t: string, from: number): boolean {
  let at = from;
  for (const ch of rest) {
    const i = t.indexOf(ch, at);
    if (i === -1) return false;
    at = i + 1;
  }
  return true;
}

/** Score `q` against one text; 0 = no match. Higher is better. */
function scoreText(rawQ: string, rawT: string): number {
  const q = norm(rawQ).replace(/\s+/g, "");
  const t = norm(rawT);
  if (!q) return 1;
  const pos = positions(q, t);
  if (!pos) return 0;
  let s = 0;
  for (let k = 0; k < pos.length; k++) {
    const i = pos[k];
    s += 1;
    if (isWordStart(t, i)) s += 8;
    if (k > 0 && pos[k - 1] === i - 1) s += 5;
    if (k > 0) s -= Math.min(3, (i - pos[k - 1] - 1) * 0.5); // gaps cost a little
  }
  const compact = t.replace(/\s+/g, "");
  if (compact === q || t === q) s += 250;
  else if (t.startsWith(q)) s += 200;
  else if (pos.length && pos[pos.length - 1] - pos[0] === pos.length - 1) s += isWordStart(t, pos[0]) ? 150 : 100;
  s -= t.length * 0.1; // shorter labels win ties
  return Math.max(s, 0.01);
}

/** Fuzzy score of a query against a command: the label counts most, then keywords,
 *  then the section. A multi-word query also matches when every word hits some field.
 *  0 means no match; an empty query scores 1 for everything. */
export function score(query: string, cmd: PaletteCommand): number {
  const q = query.trim();
  if (!q) return 1;
  const fields: [string, number][] = [
    [cmd.label, 1],
    ...(cmd.keywords ?? []).map((k): [string, number] => [k, 0.7]),
    [cmd.section, 0.5],
  ];
  let best = 0;
  for (const [text, w] of fields) best = Math.max(best, scoreText(q, text) * w);
  const words = q.split(/\s+/);
  if (words.length > 1) {
    let sum = 0;
    for (const word of words) {
      let wb = 0;
      for (const [text, w] of fields) wb = Math.max(wb, scoreText(word, text) * w);
      if (wb === 0) {
        sum = 0;
        break;
      }
      sum += wb;
    }
    best = Math.max(best, sum * 0.9);
  }
  return best;
}

/** Commands that match `query`, best first (ties keep the given order). An empty query
 *  keeps the given order but groups commands by section, sections in first-seen order. */
export function filterCommands(query: string, cmds: PaletteCommand[]): PaletteCommand[] {
  if (!query.trim()) {
    const order: string[] = [];
    const by = new Map<string, PaletteCommand[]>();
    for (const c of cmds) {
      if (!by.has(c.section)) {
        by.set(c.section, []);
        order.push(c.section);
      }
      by.get(c.section)!.push(c);
    }
    return order.flatMap((s) => by.get(s)!);
  }
  return cmds
    .map((cmd, i) => ({ cmd, i, s: score(query, cmd) }))
    .filter((r) => r.s > 0)
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((r) => r.cmd);
}

/** Indices into `label` to highlight for `query` (empty when only keywords matched). */
export function matchIndices(query: string, label: string): number[] {
  const q = norm(query).replace(/\s+/g, "");
  if (!q) return [];
  return positions(q, norm(label)) ?? [];
}

/** The palette's rows: section headers only for an empty query (ranked results read as
 *  one list), then the free-text "Ask SYRAX" row whenever there is a query. */
export function paletteRows(query: string, cmds: PaletteCommand[]): PaletteRow[] {
  const q = query.trim();
  const list = filterCommands(q, cmds);
  const rows: PaletteRow[] = [];
  let section: string | null = null;
  for (const cmd of list) {
    if (!q && cmd.section !== section) {
      section = cmd.section;
      rows.push({ kind: "header", section });
    }
    rows.push({ kind: "cmd", cmd, match: matchIndices(q, cmd.label) });
  }
  if (q) rows.push({ kind: "ask", query: q });
  return rows;
}

/** True for rows the keyboard can land on (not headers, not disabled commands). */
export function selectable(row: PaletteRow): boolean {
  return row.kind === "ask" || (row.kind === "cmd" && !row.cmd.disabled);
}

/** The id a row runs with, or null when it cannot run. */
export function rowId(row: PaletteRow): string | null {
  if (row.kind === "ask") return ASK_PREFIX + row.query;
  if (row.kind === "cmd" && !row.cmd.disabled) return row.cmd.id;
  return null;
}

/** Move `delta` steps through `count` items with wrap-around; -1 when there are none.
 *  From "nothing selected" (current < 0), down lands on the first and up on the last. */
export function nextIndex(current: number, delta: number, count: number): number {
  if (count <= 0) return -1;
  if (current < 0 || current >= count) return delta < 0 ? count - 1 : 0;
  return (((current + delta) % count) + count) % count;
}
