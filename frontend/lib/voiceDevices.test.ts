import assert from "node:assert/strict";
import { test } from "node:test";

import { DEFAULT_PREFS, loadAudioPrefs, mapDevices, micConstraints, pickDevice, saveAudioPrefs } from "./audioDevices.ts";
import { isTypingElement, keyLabel, pttKeyAllowed, pttStarts } from "./pushToTalk.ts";

const dev = (deviceId: string, kind: string, label = "") => ({ deviceId, kind, label, groupId: "g" });

test("devices: the default comes first, pseudo devices and duplicates are dropped", () => {
  const list = mapDevices(
    [
      dev("default", "audioinput", "Default - USB Mic"),
      dev("communications", "audioinput", "Communications - USB Mic"),
      dev("usb", "audioinput", "USB Mic"),
      dev("usb", "audioinput", "USB Mic"),
      dev("spk", "audiooutput", "Speakers"),
    ],
    "audioinput",
  );
  assert.deepEqual(list.options, [
    { id: "", label: "System default" },
    { id: "usb", label: "USB Mic" },
  ]);
  assert.equal(list.needsPermission, false);
});

test("devices: empty labels are numbered and ask for permission", () => {
  const list = mapDevices([dev("a", "audiooutput"), dev("b", "audiooutput", "  ")], "audiooutput");
  assert.deepEqual(
    list.options.map((o) => o.label),
    ["System default", "Speaker 1", "Speaker 2"],
  );
  assert.equal(list.needsPermission, true);
});

test("devices: before permission Firefox and Safari give empty ids, only the default is offered", () => {
  const list = mapDevices([dev("", "audioinput"), dev("", "audioinput")], "audioinput");
  assert.deepEqual(list.options, [{ id: "", label: "System default" }]);
  assert.equal(list.needsPermission, true);
  assert.equal(mapDevices([], "audioinput").needsPermission, false);
});

test("devices: a saved device that is gone falls back to the default", () => {
  const { options } = mapDevices([dev("usb", "audioinput", "USB")], "audioinput");
  assert.equal(pickDevice(options, "usb"), "usb");
  assert.equal(pickDevice(options, "unplugged"), "");
});

test("mic constraints carry the chosen device as an ideal, not exact", () => {
  assert.equal(micConstraints().deviceId, undefined);
  assert.deepEqual(micConstraints("usb").deviceId, { ideal: "usb" });
  assert.equal(micConstraints("usb").echoCancellation, true);
});

test("prefs: round trip, bad data and throwing storage", () => {
  const mem = new Map<string, string>();
  const store = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) };
  assert.equal(saveAudioPrefs({ micId: "m", speakerId: "s", pttKey: "F2" }, store), true);
  assert.deepEqual(loadAudioPrefs(store), { micId: "m", speakerId: "s", pttKey: "F2" });
  mem.set("syrax.audio", "{not json");
  assert.deepEqual(loadAudioPrefs(store), DEFAULT_PREFS);
  mem.set("syrax.audio", JSON.stringify({ micId: 3, pttKey: "" }));
  assert.deepEqual(loadAudioPrefs(store), DEFAULT_PREFS);
  const broken = {
    getItem: () => {
      throw new Error("SecurityError");
    },
    setItem: () => {
      throw new Error("QuotaExceededError");
    },
  };
  assert.deepEqual(loadAudioPrefs(broken), DEFAULT_PREFS);
  assert.equal(saveAudioPrefs(DEFAULT_PREFS, broken), false);
  assert.equal(saveAudioPrefs(DEFAULT_PREFS, null), false);
  assert.deepEqual(loadAudioPrefs(null), DEFAULT_PREFS);
});

test("push-to-talk never starts while typing", () => {
  const input = { tagName: "INPUT", type: "text" };
  assert.equal(pttStarts({ code: "Space", target: input }, "Space"), false);
  assert.equal(pttStarts({ code: "Space", target: { tagName: "TEXTAREA" } }, "Space"), false);
  assert.equal(pttStarts({ code: "Space", target: { tagName: "DIV", isContentEditable: true } }, "Space"), false);
  assert.equal(pttStarts({ code: "F2", target: input }, "F2"), false);
  assert.equal(isTypingElement({ tagName: "INPUT", type: "checkbox" }), false);
  assert.equal(isTypingElement({ tagName: "SELECT" }), true);
});

test("push-to-talk: the chosen key on the page, no repeat, no modifier", () => {
  const body = { tagName: "BODY" };
  assert.equal(pttStarts({ code: "Space", target: body }, "Space"), true);
  assert.equal(pttStarts({ code: "Space", target: null }, "Space"), true);
  assert.equal(pttStarts({ code: "Space", repeat: true, target: body }, "Space"), false);
  assert.equal(pttStarts({ code: "Space", ctrlKey: true, target: body }, "Space"), false);
  assert.equal(pttStarts({ code: "KeyT", target: body }, "Space"), false);
  assert.equal(pttStarts({ code: "KeyT", target: body }, "KeyT"), true);
});

test("push-to-talk: Space on a focused button presses the button; another key still talks there", () => {
  const button = { tagName: "BUTTON" };
  assert.equal(pttStarts({ code: "Space", target: button }, "Space"), false);
  assert.equal(pttStarts({ code: "Space", target: { tagName: "DIV", getAttribute: () => "button" } }, "Space"), false);
  assert.equal(pttStarts({ code: "F2", target: button }, "F2"), true);
});

test("push-to-talk keys: HUD shortcuts are refused, labels are short", () => {
  assert.equal(pttKeyAllowed("KeyM"), false);
  assert.equal(pttKeyAllowed("Escape"), false);
  assert.equal(pttKeyAllowed(""), false);
  assert.equal(pttKeyAllowed("Space"), true);
  assert.equal(pttKeyAllowed("F2"), true);
  assert.equal(keyLabel("Space"), "SPACE");
  assert.equal(keyLabel("KeyT"), "T");
  assert.equal(keyLabel("Digit4"), "4");
  assert.equal(keyLabel("Backquote"), "`");
  assert.equal(keyLabel("F2"), "F2");
});
