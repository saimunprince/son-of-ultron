import assert from "node:assert/strict";
import { test } from "node:test";

import { activityLine, arcSegments, formatElapsed, phaseIndex, segmentStates, truncate } from "./taskArc.ts";

test("elapsed reads like a stopwatch", () => {
  assert.equal(formatElapsed(0), "0:00");
  assert.equal(formatElapsed(23_400), "0:23");
  assert.equal(formatElapsed(83_000), "1:23");
  assert.equal(formatElapsed(3_723_000), "1:02:03");
  assert.equal(formatElapsed(-5), "0:00");
  assert.equal(formatElapsed(Number.NaN), "0:00");
});

test("segments: done before, lit at, dark after the phase", () => {
  assert.equal(phaseIndex("act"), 2);
  assert.equal(phaseIndex(null), -1);
  assert.deepEqual(segmentStates("act"), ["done", "done", "current", "todo", "todo"]);
  assert.deepEqual(segmentStates("understand"), ["current", "todo", "todo", "todo", "todo"]);
  assert.deepEqual(segmentStates("verify"), ["done", "done", "done", "done", "current"]);
  assert.deepEqual(segmentStates(null), ["todo", "todo", "todo", "todo", "todo"]);
});

test("truncate keeps a path's tail and a sentence's head", () => {
  assert.equal(truncate("short", 10), "short");
  assert.equal(truncate("/home/me/projects/site/index.html", 14), "…te/index.html");
  assert.equal(truncate("https://example.com/a/b/c/page", 10), "…/b/c/page");
  assert.equal(truncate("open the weather page now", 12), "open the we…");
  assert.equal(truncate("  many   spaces  ", 20), "many spaces");
  for (const max of [5, 9, 14]) assert.ok(truncate("/a/very/long/path/to/a/file.txt", max).length <= max);
});

test("activity line joins tool and target within the limit", () => {
  assert.equal(activityLine(null, null), "");
  assert.equal(activityLine("browser", null), "browser");
  assert.equal(activityLine(null, "notes.txt"), "notes.txt");
  assert.equal(activityLine("files", "notes.txt"), "files · notes.txt");
  const line = activityLine("browser", "https://example.com/some/really/deep/page/index.html", 30);
  assert.ok(line.startsWith("browser · …"));
  assert.ok(line.length <= 30, line);
});

test("arc: five ordered segments, a smile that dips in the middle", () => {
  const segs = arcSegments(5);
  assert.equal(segs.length, 5);
  for (const s of segs) assert.match(s.d, /^M [\d.]+ [\d.]+ A [\d.]+ [\d.]+ 0 0 0 [\d.]+ [\d.]+$/);
  const xs = segs.map((s) => s.mid.x);
  assert.deepEqual([...xs].sort((a, b) => a - b), xs);
  assert.ok(segs[2].mid.y > segs[0].mid.y && segs[2].mid.y > segs[4].mid.y);
  assert.ok(Math.abs(segs[0].mid.y - segs[4].mid.y) < 0.02);
  assert.ok(Math.abs(segs[2].mid.x - 180) < 0.02);
  assert.deepEqual(arcSegments(0), []);
});
