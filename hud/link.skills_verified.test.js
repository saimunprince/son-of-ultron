// The HUD says "<n> SKILLS I BUILT AND TESTED MYSELF" (hud.html thought pool). It counted every skill row, including
// NOT_TESTED, FAILED and DISABLED ones; skills.py gives VERIFIED only after a passing test run, so only those count.
// s.skills (the whole list, the SELF row's SKILLS) is unchanged.
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("./link.js");

// server.py skills -> core.skills.list(): registry rows {name, version, purpose, path, status, tests_passed, tests_failed, ...}
const row = (name, status, passed, failed) => ({ name, version: 1, purpose: name, path: "backend/skills/" + name, status, tests_passed: passed, tests_failed: failed });

test("only VERIFIED skills count as built and tested", () => {
  const s = L.initial();
  assert.equal(s.skillsVerified, null, "unknown until the list arrives");
  L.reduce(s, { type: "skills", skills: [row("disk_usage", "VERIFIED", 4, 0), row("pdf_text", "FAILED", 2, 1), row("draft", "NOT_TESTED", 0, 0), row("old", "DISABLED", 3, 0), row("ping", "VERIFIED", 2, 0)] }, 1);
  assert.equal(s.skillsVerified, 2);
  assert.equal(s.skills, 5, "the whole list is still the SKILLS count");
  L.reduce(s, { type: "skills", skills: [] }, 2);
  assert.equal(s.skillsVerified, 0);
});
