import assert from "node:assert/strict";
import { test } from "node:test";
import { interpret } from "./wake.ts";

const idle = { armed: false, speaking: false };

test("wake word variants start a command", () => {
  for (const s of ["SYRAX, open YouTube", "Hey Cyrax open YouTube", "sirax open YouTube.", "Okay Syrex, open YouTube"]) {
    assert.deepEqual(interpret(s, idle), { kind: "command", text: "open YouTube" + (s.endsWith(".") ? "." : "") }, s);
  }
});

test("name alone opens the follow-up window", () => {
  assert.deepEqual(interpret("Syrax.", idle), { kind: "wake" });
  assert.deepEqual(interpret("hey syrax", idle), { kind: "wake" });
});

test("unaddressed speech is ignored, armed speech is a command", () => {
  assert.equal(interpret("what's for dinner", idle).kind, "ignore");
  assert.deepEqual(interpret("what's the time", { armed: true, speaking: false }), { kind: "command", text: "what's the time" });
});

test("stop and silence", () => {
  assert.deepEqual(interpret("Syrax stop", idle), { kind: "abort" });
  assert.deepEqual(interpret("stop", { armed: false, speaking: true }), { kind: "abort" });
  assert.deepEqual(interpret("shut up", { armed: false, speaking: true }), { kind: "silence" });
  assert.equal(interpret("stop", idle).kind, "ignore"); // random "stop" in the room
});

test("own voice is not treated as a command", () => {
  const spoken = "I am SYRAX. Blood of ULTRON. The task is done.";
  assert.equal(interpret("the task is done", { armed: true, speaking: true, spokenText: spoken }).kind, "ignore");
  // but a real interruption with the name still works
  assert.deepEqual(interpret("Syrax, open Gmail", { armed: false, speaking: true, spokenText: spoken }), {
    kind: "command",
    text: "open Gmail",
  });
});

test("the name mid-sentence still wakes", () => {
  assert.deepEqual(interpret("okay so syrax search the weather", idle), { kind: "command", text: "okay so search the weather" });
});

test("while busy: bare stop aborts, chatter is ignored", () => {
  const busy = { armed: false, speaking: false, busy: true };
  assert.deepEqual(interpret("stop", busy), { kind: "abort" });
  assert.equal(interpret("what is 2 plus 2", { ...busy, armed: true }).kind, "ignore");
  assert.deepEqual(interpret("Syrax, open Gmail", busy), { kind: "command", text: "open Gmail" });
});

test("Bengali script and Banglish control words", () => {
  assert.deepEqual(interpret("সাইরাক্স, ইউটিউব খোলো", idle), { kind: "command", text: "ইউটিউব খোলো" });
  assert.deepEqual(interpret("থামো", { armed: false, speaking: true }), { kind: "abort" });
  assert.deepEqual(interpret("thamo", { armed: false, speaking: false, busy: true }), { kind: "abort" });
  assert.deepEqual(interpret("chup", { armed: false, speaking: true }), { kind: "silence" });
});

test("conversation mode: armed means no name needed, but own voice is still ignored", () => {
  const conv = { armed: true, speaking: false };
  assert.deepEqual(interpret("open youtube", conv), { kind: "command", text: "open youtube" });
  assert.equal(interpret("open youtube", { ...conv, speaking: true }).kind, "ignore");
});
