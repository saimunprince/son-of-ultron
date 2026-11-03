import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CAPTION_MAX_CHARS,
  CAPTION_MAX_MS,
  CAPTION_MIN_MS,
  chunkCaption,
  cleanCaption,
  planCaption,
  readingMs,
} from "./captions.ts";

test("empty, blank and null-ish text give no chunks", () => {
  assert.deepEqual(chunkCaption(""), []);
  assert.deepEqual(chunkCaption("   \n\t  "), []);
  assert.deepEqual(chunkCaption(undefined as unknown as string), []);
});

test("a short sentence is one chunk, whitespace collapsed", () => {
  assert.deepEqual(chunkCaption("  Done.   The   file is   saved.  "), ["Done. The file is saved."]);
});

test("sentences split on . ! ? … and the Bengali danda", () => {
  const long = "The deployment finished without a single warning on any of the servers.";
  const chunks = chunkCaption(`${long} Should I also restart the background workers now? Yes, I can do that right after the deploy!`);
  assert.deepEqual(chunks, [long, "Should I also restart the background workers now?", "Yes, I can do that right after the deploy!"]);
  assert.deepEqual(chunkCaption("কাজ শেষ হয়েছে এবং ফাইলটি সংরক্ষণ করা হয়েছে। এখন পরের ধাপে যাচ্ছি ভাই।", 60), [
    "কাজ শেষ হয়েছে এবং ফাইলটি সংরক্ষণ করা হয়েছে।",
    "এখন পরের ধাপে যাচ্ছি ভাই।",
  ]);
});

test("decimals, versions and abbreviations glued to text do not end a sentence", () => {
  const chunks = chunkCaption("Upgraded Node to v22.4.1 and the score is 92.5 percent, e.g. better than last week.");
  assert.equal(chunks.length, 1);
  assert.match(chunks[0], /v22\.4\.1/);
  assert.match(chunks[0], /92\.5/);
});

test("every chunk respects maxChars, splitting on commas then spaces", () => {
  const text =
    "I checked the logs, the metrics dashboard, the error tracker, the queue depth and the database replicas, and everything looks healthy across all three regions right now";
  for (const max of [24, 40, 60, CAPTION_MAX_CHARS]) {
    const chunks = chunkCaption(text, max);
    for (const c of chunks) assert.ok(c.length <= max, `"${c}" is ${c.length} > ${max}`);
    assert.equal(chunks.join(" ").replace(/\s+/g, " "), text);
  }
  // Commas are preferred break points.
  const byClause = chunkCaption(text, 60);
  assert.ok(byClause.some((c) => c.endsWith(",")), JSON.stringify(byClause));
});

test("a word longer than maxChars is hard-cut", () => {
  const w = "x".repeat(50);
  const chunks = chunkCaption(w, 20);
  assert.deepEqual(chunks, ["x".repeat(20), "x".repeat(20), "x".repeat(10)]);
});

test("code fences become one [code] marker, unclosed fences too", () => {
  const text = "Here is the fix:\n```ts\nconst a = 1;\nconsole.log(a);\n```\nRun it again.";
  const chunks = chunkCaption(text);
  assert.ok(!chunks.join(" ").includes("console.log"));
  assert.match(chunks.join(" "), /\[code\]/);
  assert.match(chunks.join(" "), /Run it again\./);
  assert.ok(!cleanCaption("Try this:\n```py\nprint('hi')").includes("print"));
  assert.equal(cleanCaption("```a```\n```b```"), "[code]");
});

test("markdown is stripped: headings, lists, emphasis, links, images, quotes, tables", () => {
  const md = [
    "## Summary",
    "- **Fixed** the _login_ bug",
    "1. Read [the docs](https://example.com/docs)",
    "> quoted ~~old~~ text",
    "![chart](https://x.y/a.png)",
    "| name | state |",
    "| --- | --- |",
    "| api | up |",
    "---",
    "Use `npm test` and keep my_var_name *as is*.",
  ].join("\n");
  const clean = cleanCaption(md);
  assert.equal(
    clean,
    [
      "Summary",
      "Fixed the login bug",
      "Read the docs",
      "quoted old text",
      "name, state",
      "api, up",
      "Use npm test and keep my_var_name as is.",
    ].join("\n"),
  );
});

test("line breaks act as sentence boundaries", () => {
  assert.deepEqual(chunkCaption("First item in the list here\nSecond item in the list here", 40), [
    "First item in the list here",
    "Second item in the list here",
  ]);
});

test("URLs become [link]; trailing punctuation survives", () => {
  assert.equal(cleanCaption("See https://github.com/a/b?x=1. Or www.example.org, later."), "See [link]. Or [link], later.");
  assert.equal(cleanCaption("Open <https://example.com/x> now"), "Open [link] now");
});

test("long inline code becomes [code]", () => {
  assert.equal(cleanCaption("Run `" + "a".repeat(60) + "` now"), "Run [code] now");
});

test("short neighbouring sentences merge, long ones stay apart", () => {
  assert.deepEqual(chunkCaption("Okay. Done. All good."), ["Okay. Done. All good."]);
  const a = "This first sentence is comfortably long enough on its own.";
  const b = "And this second one is long enough as well, honestly.";
  assert.deepEqual(chunkCaption(`${a} ${b}`), [a, b]);
});

test("readingMs is ~60 ms per char, clamped to 1.4-5 s", () => {
  assert.equal(readingMs(""), CAPTION_MIN_MS);
  assert.equal(readingMs("Hi."), CAPTION_MIN_MS);
  assert.equal(readingMs("x".repeat(40)), 2400);
  assert.equal(readingMs("x".repeat(500)), CAPTION_MAX_MS);
  assert.equal(readingMs("   padded   "), CAPTION_MIN_MS);
  assert.ok(readingMs("x".repeat(30)) < readingMs("x".repeat(60)));
});

test("planCaption keeps the first chunks and flags the rest as truncated", () => {
  const text = Array.from({ length: 8 }, (_, i) => `This is sentence number ${i + 1}, long enough to stand alone.`).join(" ");
  const plan = planCaption(text);
  assert.equal(plan.chunks.length, 4);
  assert.equal(plan.truncated, true);
  assert.deepEqual(plan.durations, plan.chunks.map(readingMs));
  assert.match(plan.chunks[0], /number 1,/);

  const short = planCaption("All done.");
  assert.deepEqual(short, { chunks: ["All done."], durations: [CAPTION_MIN_MS], truncated: false });
  assert.deepEqual(planCaption(""), { chunks: [], durations: [], truncated: false });
  assert.equal(planCaption(text, 0).chunks.length, 1);
});
