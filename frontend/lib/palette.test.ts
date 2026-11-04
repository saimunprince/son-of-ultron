import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ASK_PREFIX,
  filterCommands,
  matchIndices,
  nextIndex,
  paletteRows,
  rowId,
  score,
  selectable,
  type PaletteCommand,
} from "./palette.ts";

const cmds: PaletteCommand[] = [
  { id: "panel.brain", label: "Open Brain settings", section: "Panels", hint: "B" },
  { id: "safety.estop", label: "Emergency stop", section: "Safety", keywords: ["estop", "kill", "halt"], danger: true },
  { id: "panel.self", label: "Open Self model", section: "Panels", hint: "S" },
  { id: "view.zoomIn", label: "Zoom in", section: "View", hint: "+" },
  { id: "theme.jarvis", label: "Theme: JARVIS", section: "Appearance", keywords: ["cyan", "calm"] },
  { id: "view.zoomOut", label: "Zoom out", section: "View", hint: "−" },
  { id: "mind.skills", label: "Open MIND · Skills", section: "Mind" },
  { id: "auto.up", label: "Autonomy level up", section: "Autonomy", disabled: true },
];

const ids = (list: PaletteCommand[]) => list.map((c) => c.id);

test("empty query: everything matches, grouped by section in first-seen order", () => {
  assert.equal(score("", cmds[0]), 1);
  assert.equal(score("   ", cmds[0]), 1);
  assert.deepEqual(ids(filterCommands("", cmds)), [
    "panel.brain",
    "panel.self",
    "safety.estop",
    "view.zoomIn",
    "view.zoomOut",
    "theme.jarvis",
    "mind.skills",
    "auto.up",
  ]);
});

test("no match scores 0 and is filtered out", () => {
  assert.equal(score("xyzzy", cmds[0]), 0);
  assert.deepEqual(filterCommands("xyzzy", cmds), []);
});

test("subsequence matching is case-insensitive", () => {
  assert.ok(score("OBS", cmds[0]) > 0); // Open Brain Settings
  assert.ok(score("zmin", cmds[3]) > 0);
  assert.equal(score("nimz", cmds[3]), 0); // order matters
});

test("word-start initials beat scattered letters", () => {
  const a: PaletteCommand = { id: "a", label: "Open Brain settings", section: "x" };
  const b: PaletteCommand = { id: "b", label: "Globes", section: "x" };
  assert.ok(score("obs", a) > score("obs", b));
});

test("consecutive characters beat gapped ones", () => {
  const a: PaletteCommand = { id: "a", label: "zoom", section: "x" };
  const b: PaletteCommand = { id: "b", label: "z-o-o-m", section: "x" };
  assert.ok(score("zoom", a) > score("zoom", b));
});

test("exact > prefix > word-substring > substring", () => {
  const mk = (label: string): PaletteCommand => ({ id: label, label, section: "x" });
  const exact = score("zoom", mk("zoom"));
  const prefix = score("zoom", mk("zoom in"));
  const word = score("zoom", mk("reset zoom"));
  const inner = score("oom", mk("reset zoom"));
  assert.ok(exact > prefix, "exact beats prefix");
  assert.ok(prefix > word, "prefix beats a later word");
  assert.ok(word > inner, "a word start beats mid-word");
});

test("keywords match when the label does not", () => {
  const estop = cmds[1];
  assert.ok(score("kill", estop) > 0);
  assert.ok(score("halt", estop) > 0);
  assert.equal(ids(filterCommands("kill", cmds))[0], "safety.estop"); // "s-kill-s" trails it
});

test("a label hit outranks the same hit in keywords only", () => {
  const label: PaletteCommand = { id: "l", label: "Calm mode", section: "x" };
  const kw: PaletteCommand = { id: "k", label: "Theme: JARVIS", section: "x", keywords: ["calm"] };
  assert.deepEqual(ids(filterCommands("calm", [kw, label])), ["l", "k"]);
});

test("the section is searchable but weighs least", () => {
  assert.ok(score("appearance", cmds[4]) > 0);
  const inLabel: PaletteCommand = { id: "a", label: "View logs", section: "x" };
  const inSection: PaletteCommand = { id: "b", label: "Something", section: "View" };
  assert.deepEqual(ids(filterCommands("view", [inSection, inLabel])), ["a", "b"]);
});

test("multi-word queries match words in any order across fields", () => {
  assert.ok(score("skills mind", cmds[6]) > 0);
  assert.ok(score("zoom view", cmds[3]) > 0); // label word + section word
  assert.equal(score("zoom banana", cmds[3]), 0);
});

test("ranking: best first, ties keep the given order", () => {
  const out = ids(filterCommands("zoom", cmds));
  assert.deepEqual(out, ["view.zoomIn", "view.zoomOut"]);
  assert.deepEqual(ids(filterCommands("open", cmds)).slice(0, 3).sort(), ["mind.skills", "panel.brain", "panel.self"]);
  const twins: PaletteCommand[] = [
    { id: "b", label: "Open beta", section: "x" },
    { id: "a", label: "Open alfa", section: "x" },
  ];
  assert.deepEqual(ids(filterCommands("open", twins)), ["b", "a"]);
});

test("diacritics are ignored", () => {
  const c: PaletteCommand = { id: "c", label: "Café réglages", section: "x" };
  assert.ok(score("cafe regl", c) > 0);
});

test("matchIndices: contiguous run at a word start, else a subsequence", () => {
  assert.deepEqual(matchIndices("zoom", "Reset zoom"), [6, 7, 8, 9]);
  assert.deepEqual(matchIndices("obs", "Open Brain settings"), [0, 5, 11]);
  assert.deepEqual(matchIndices("", "Zoom"), []);
  assert.deepEqual(matchIndices("kill", "Emergency stop"), []);
});

test("matchIndices prefers word-start chars but never breaks the match", () => {
  // "s" could jump to "Stop" but then "t" still fits after it
  assert.deepEqual(matchIndices("st", "Emergency stop"), [10, 11]);
  // jumping to the word start of "o" in "out" would leave no room for "i"
  assert.deepEqual(matchIndices("zoi", "zoom in out"), [0, 1, 5]);
});

test("paletteRows: headers only with an empty query, no ask row", () => {
  const rows = paletteRows("", cmds.slice(0, 3));
  assert.deepEqual(
    rows.map((r) => (r.kind === "header" ? `#${r.section}` : r.kind === "cmd" ? r.cmd.id : "ask")),
    ["#Panels", "panel.brain", "panel.self", "#Safety", "safety.estop"],
  );
});

test("paletteRows: a query gives a flat ranked list plus the ask row last", () => {
  const rows = paletteRows("  zoom ", cmds);
  assert.deepEqual(
    rows.map((r) => r.kind),
    ["cmd", "cmd", "ask"],
  );
  const ask = rows[rows.length - 1];
  assert.deepEqual(ask, { kind: "ask", query: "zoom" });
  assert.equal(rowId(ask), `${ASK_PREFIX}zoom`);
});

test("paletteRows: nothing matches leaves just the ask row", () => {
  const rows = paletteRows("what is the weather", cmds);
  assert.equal(rows.length, 1);
  assert.equal(rowId(rows[0]), "ask:what is the weather");
});

test("selectable / rowId skip headers and disabled commands", () => {
  const header = { kind: "header", section: "x" } as const;
  const off = { kind: "cmd", cmd: cmds[7], match: [] } as const;
  const on = { kind: "cmd", cmd: cmds[0], match: [] } as const;
  assert.equal(selectable(header), false);
  assert.equal(selectable(off), false);
  assert.equal(selectable(on), true);
  assert.equal(rowId(header), null);
  assert.equal(rowId(off), null);
  assert.equal(rowId(on), "panel.brain");
});

test("nextIndex wraps both ways", () => {
  assert.equal(nextIndex(0, 1, 3), 1);
  assert.equal(nextIndex(2, 1, 3), 0);
  assert.equal(nextIndex(0, -1, 3), 2);
  assert.equal(nextIndex(1, -1, 3), 0);
  assert.equal(nextIndex(1, 7, 3), 2);
  assert.equal(nextIndex(1, -7, 3), 0);
});

test("nextIndex edge cases: empty list, nothing selected, stale index", () => {
  assert.equal(nextIndex(0, 1, 0), -1);
  assert.equal(nextIndex(-1, 1, 0), -1);
  assert.equal(nextIndex(-1, 1, 4), 0);
  assert.equal(nextIndex(-1, -1, 4), 3);
  assert.equal(nextIndex(9, 1, 4), 0);
  assert.equal(nextIndex(0, 0, 1), 0);
});
