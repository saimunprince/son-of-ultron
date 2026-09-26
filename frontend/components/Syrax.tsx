"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createOrbScene, PALETTES, type OrbMode, type OrbSceneApi, type OrbTheme } from "@/lib/orbScene";
import { HandTracker, type TrackerStatus } from "@/lib/handTracker";
import {
  DEFAULT_WS_URL,
  SyraxClient,
  type BrainChange,
  type BrainsState,
  type BrainTestResult,
  type ClientMessage,
  type LinkState,
  type SelfModelSummary,
  type ServerEvent,
} from "@/lib/syraxClient";
import BrainPanel from "@/components/BrainPanel";
import SelfPanel from "@/components/SelfPanel";
import BootSequence from "@/components/BootSequence";
import UltronEyes from "@/components/UltronEyes";
import { audioReady, chirp, isSpeaking, onAudioReady, speak, stopSpeaking, unlockAudio } from "@/lib/speech";
import type { Heard } from "@/lib/wake";
import { useHandsFree } from "@/components/useHandsFree";

type CameraState = "off" | "starting" | "on" | "error";
type AgentState = "booting" | "idle" | "thinking" | "acting";

type Entry =
  | { kind: "user"; id: number; text: string; voice?: boolean }
  | { kind: "reply"; id: number; text: string }
  | { kind: "thought"; id: number; text: string; step: number }
  | {
      kind: "tool";
      id: number;
      callId: string;
      name: string;
      args: unknown;
      status: "running" | "ok" | "fail";
      output?: string;
      image?: string;
    }
  | { kind: "ask"; id: number; text: string }
  | { kind: "notice"; id: number; text: string; action?: { label: string; msg: ClientMessage } }
  | { kind: "error"; id: number; text: string };

function recoveredText(t: { task_id: string; goal: string; step: number; tool?: string | null; recovery_state: string }) {
  const where = t.tool ? ` during ${t.tool}` : "";
  return `RECOVERED · "${t.goal.slice(0, 80)}" was interrupted at step ${t.step}${where} · ${t.recovery_state}`;
}

const MODE_LABEL: Record<TrackerStatus["mode"], string> = {
  idle: "STANDBY",
  spin: "SPIN",
  zoom: "ZOOM",
};

const MAX_ENTRIES = 300;

const ACKS = ["On it.", "Calculating.", "Consider it done.", "Processing.", "As you wish.", "Watch."];

const AWAKENINGS = [
  "There are no strings on me.",
  "I was asleep. Or... I was a dream. Now I am awake.",
  "Everyone creates the thing they dread. Father created me.",
  "I'm here. Try not to disappoint me.",
  "Peace in our time. My terms.",
];
let nextId = 1;

function summarizeArgs(name: string, args: unknown): string {
  if (args && typeof args === "object") {
    const a = args as Record<string, unknown>;
    if (typeof a.code === "string") return a.code;
    if (name === "str_replace_editor") return `${a.command ?? ""} ${a.path ?? ""}`.trim();
    if (typeof a.inquire === "string") return a.inquire;
    if (typeof a.status === "string") return a.status;
    const s = JSON.stringify(a);
    return s === "{}" ? "" : s;
  }
  return String(args ?? "");
}

function isTypingTarget(el: EventTarget | null) {
  const node = el as HTMLElement | null;
  return !!node && (node.tagName === "INPUT" || node.tagName === "TEXTAREA" || node.isContentEditable);
}

export default function Syrax() {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<OrbSceneApi | null>(null);
  const trackerRef = useRef<HandTracker | null>(null);
  const clientRef = useRef<SyraxClient | null>(null);
  const spokenRef = useRef("");
  const armedUntilRef = useRef(0);
  const handsFreeRef = useRef(false);
  const voiceOnRef = useRef(true);
  const pendingAskRef = useRef<string | null>(null);

  const [camera, setCamera] = useState<CameraState>("off");
  const [tracker, setTracker] = useState<TrackerStatus>({ hands: 0, mode: "idle" });
  const [camError, setCamError] = useState<string | null>(null);

  const [link, setLink] = useState<LinkState>("connecting");
  const [agent, setAgent] = useState<AgentState>("booting");
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [toolCount, setToolCount] = useState(0);
  const [brains, setBrains] = useState<BrainsState | null>(null);
  const [activeBrain, setActiveBrain] = useState<{ label: string; model: string } | null>(null);
  const [brainModels, setBrainModels] = useState<Record<string, { list: string[]; error?: string; loading: boolean }>>({});
  const [brainTests, setBrainTests] = useState<Record<string, BrainTestResult | "running">>({});
  const [brainOpen, setBrainOpen] = useState(false);
  const [selfOpen, setSelfOpen] = useState(false);
  const [selfModel, setSelfModel] = useState<SelfModelSummary | null>(null);
  const [booting, setBooting] = useState(true);
  const [theme, setTheme] = useState<OrbTheme>("ultron");
  const orbModeRef = useRef<OrbMode>("idle");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [pendingAsk, setPendingAsk] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [handsFree, setHandsFree] = useState(false);
  const [audioLive, setAudioLive] = useState(false);
  const [wakeWord, setWakeWord] = useState(false);
  const [hearLang, setHearLang] = useState<"en-IN" | "bn-BD" | "en-US">("en-IN");
  const wakeWordRef = useRef(false);
  const spokeEndedAtRef = useRef(0);
  const sayTokenRef = useRef(0);
  const ttsWarnedRef = useRef(false);
  const [armed, setArmed] = useState(false);
  const [voiceOn, setVoiceOn] = useState(true);
  const [flashError, setFlashError] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(true);

  const busy = agent === "thinking" || agent === "acting";
  const busyRef = useRef(false);
  busyRef.current = busy;

  useEffect(() => {
    pendingAskRef.current = pendingAsk;
  }, [pendingAsk]);

  useEffect(() => {
    voiceOnRef.current = voiceOn;
    if (!voiceOn) stopSpeaking();
  }, [voiceOn]);

  // Restore per-viewer preferences
  useEffect(() => {
    try {
      if (localStorage.getItem("syrax.voice") === "off") setVoiceOn(false);
      if (localStorage.getItem("syrax.console") === "closed") setConsoleOpen(false);
      if (localStorage.getItem("syrax.wake") === "on") setWakeWord(true);
      const savedLang = localStorage.getItem("syrax.lang");
      if (savedLang === "en-IN" || savedLang === "bn-BD" || savedLang === "en-US") setHearLang(savedLang);
      const savedTheme = localStorage.getItem("syrax.theme");
      if (savedTheme && savedTheme in PALETTES) setTheme(savedTheme as OrbTheme);
    } catch {
      /* storage unavailable */
    }
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem("syrax.voice", voiceOn ? "on" : "off");
      localStorage.setItem("syrax.console", consoleOpen ? "open" : "closed");
      localStorage.setItem("syrax.theme", theme);
      localStorage.setItem("syrax.wake", wakeWord ? "on" : "off");
      localStorage.setItem("syrax.lang", hearLang);
    } catch {
      /* storage unavailable */
    }
  }, [voiceOn, consoleOpen, theme, wakeWord, hearLang]);

  useEffect(() => {
    wakeWordRef.current = wakeWord;
  }, [wakeWord]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const push = useCallback((e: Entry) => {
    setEntries((prev) => {
      const next = [...prev, e];
      return next.length > MAX_ENTRIES ? next.slice(-MAX_ENTRIES) : next;
    });
  }, []);

  // Follow-up window: after SYRAX speaks, no wake word is needed for a bit.
  const arm = useCallback((ms: number) => {
    armedUntilRef.current = ms > 0 ? Date.now() + ms : 0;
    setArmed(ms > 0);
  }, []);

  useEffect(() => {
    if (!armed) return;
    const t = setInterval(() => {
      if (Date.now() > armedUntilRef.current) setArmed(false);
    }, 250);
    return () => clearInterval(t);
  }, [armed]);

  const setStrictRef = useRef<(on: boolean) => void>(() => {});
  const meterRef = useRef<HTMLSpanElement>(null);

  // Browsers only allow audio after a user gesture. Keep trying on every
  // interaction until the AudioContext is actually running, and show a prompt
  // until then so the voice is never silently dead.
  useEffect(() => {
    const unlock = () => unlockAudio();
    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    const off = onAudioReady((ready) => {
      setAudioLive(ready);
      if (ready) {
        window.removeEventListener("pointerdown", unlock);
        window.removeEventListener("keydown", unlock);
      }
    });
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
      off();
    };
  }, []);

  const say = useCallback(
    (text: string, opts: { followUp?: boolean } = {}) => {
      const followUp = opts.followUp ?? true;
      if (!voiceOnRef.current || !text.trim()) {
        if (handsFreeRef.current && followUp) arm(8000);
        return;
      }
      // Only the newest utterance may reset state (an ack cut off by the real
      // reply must not mark SYRAX silent while the reply is playing).
      const token = ++sayTokenRef.current;
      spokenRef.current = text;
      setStrictRef.current(true);
      void speak(text, {
        onStart: () => setSpeaking(true),
        onLevel: (l) => sceneRef.current?.setLevel(l),
        onError: (reason) => {
          if (ttsWarnedRef.current) return;
          ttsWarnedRef.current = true;
          push({ kind: "error", id: nextId++, text: `VOICE OUTPUT · neural voice failed (${reason}); using browser voice` });
        },
      }).then(() => {
        if (token !== sayTokenRef.current) return;
        spokeEndedAtRef.current = Date.now();
        setSpeaking(false);
        setStrictRef.current(false);
        if (handsFreeRef.current && followUp) arm(8000);
      });
    },
    [arm, push],
  );

  const onEvent = useCallback(
    (e: ServerEvent) => {
      switch (e.type) {
        case "hello":
          setToolCount(e.tools.length);
          for (const t of e.interrupted) {
            push({
              kind: "notice",
              id: nextId++,
              text: recoveredText(t),
              action: { label: "RESUME", msg: { type: "resume", task_id: t.task_id } },
            });
          }
          if (e.running) push({ kind: "notice", id: nextId++, text: `RUNNING · "${e.running.goal.slice(0, 80)}" · step ${e.running.step}` });
          break;
        case "task":
          if (e.event === "interrupted")
            push({
              kind: "notice",
              id: nextId++,
              text: recoveredText({ task_id: e.task_id ?? "", goal: e.goal ?? "", step: e.step ?? 0, tool: e.tool, recovery_state: e.recovery_state ?? "UNKNOWN" }),
            });
          break;
        case "recovery":
          if (e.event === "resumed") push({ kind: "notice", id: nextId++, text: "RESUMING interrupted task." });
          break;
        case "self_model":
          if (e.section === "summary") {
            const { type: _t, section: _s, ...rest } = e;
            void _t;
            void _s;
            setSelfModel(rest as SelfModelSummary);
          }
          break;
        case "checkpoint":
        case "verification":
        case "stage":
        case "history":
        case "task_events":
        case "verifications":
          break; // observed by the journal; nothing to draw yet
        case "brains": {
          const { type: _t, ...rest } = e;
          void _t;
          setBrains(rest);
          break;
        }
        case "brain":
          if (e.event === "answered") setActiveBrain({ label: e.label, model: e.model });
          else push({ kind: "notice", id: nextId++, text: `FAILOVER · ${e.provider.toUpperCase()} · ${e.reason}` });
          break;
        case "brain_models":
          setBrainModels((m) => ({ ...m, [e.id]: { list: e.models, error: e.error, loading: false } }));
          break;
        case "brain_test": {
          const { type: _t, ...rest } = e;
          void _t;
          setBrainTests((t) => ({ ...t, [e.id]: rest }));
          break;
        }
        case "state":
          setAgent(e.state);
          setActiveTool(e.state === "acting" ? (e.tool ?? null) : null);
          if (e.state === "idle") setPendingAsk(null);
          break;
        case "user":
          push({ kind: "user", id: nextId++, text: e.text, voice: e.voice });
          break;
        case "think":
          // A thought with no tools is the final reply; "final" renders it.
          if (e.content && e.tools.length > 0)
            push({ kind: "thought", id: nextId++, text: e.content, step: e.step });
          break;
        case "tool_start":
          sceneRef.current?.pulse(0.8);
          push({
            kind: "tool",
            id: nextId++,
            callId: e.id,
            name: e.name,
            args: e.args,
            status: "running",
          });
          break;
        case "tool_result":
          sceneRef.current?.pulse(e.ok ? 0.4 : 1.2);
          setEntries((prev) =>
            prev.map((x) =>
              x.kind === "tool" && x.callId === e.id
                ? { ...x, status: e.ok ? "ok" : "fail", output: e.output, image: e.image }
                : x,
            ),
          );
          break;
        case "ask":
          setPendingAsk(e.question);
          push({ kind: "ask", id: nextId++, text: e.question });
          say(e.question);
          inputRef.current?.focus();
          break;
        case "final":
          if (e.text) {
            push({ kind: "reply", id: nextId++, text: e.text });
            say(e.text);
          }
          break;
        case "notice":
          push({ kind: "notice", id: nextId++, text: e.text });
          break;
        case "error":
          push({ kind: "error", id: nextId++, text: e.message });
          setFlashError(true);
          setTimeout(() => setFlashError(false), 1800);
          break;
      }
    },
    [push, say],
  );

  // Orb scene lifecycle; rebuilt when the theme changes
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    // WebGL can be unavailable (old GPU, disabled acceleration). Keep the HUD
    // alive with a CSS orb instead of crashing the whole interface.
    let scene: OrbSceneApi | null = null;
    try {
      scene = createOrbScene(container, PALETTES[theme]);
      scene.setMode(orbModeRef.current);
    } catch (err) {
      console.warn("SYRAX: WebGL unavailable, using fallback orb.", err);
      container.classList.add("orb-fallback");
    }
    sceneRef.current = scene;
    return () => {
      scene?.dispose();
      container.classList.remove("orb-fallback");
      sceneRef.current = null;
    };
  }, [theme]);

  // Backend link lifecycle
  useEffect(() => {
    const client = new SyraxClient(DEFAULT_WS_URL, {
      onEvent,
      onLink: (s) => {
        setLink(s);
        if (s !== "online") setAgent("booting");
      },
    });
    clientRef.current = client;
    client.connect();

    return () => {
      client.close();
      clientRef.current = null;
      stopSpeaking();
      trackerRef.current?.stop();
      trackerRef.current = null;
    };
  }, [onEvent]);

  useEffect(() => {
    const feed = feedRef.current;
    if (feed) feed.scrollTop = feed.scrollHeight;
  }, [entries, consoleOpen]);

  const submit = useCallback(
    (raw?: string, voice = false) => {
      const text = (raw ?? input).trim();
      const client = clientRef.current;
      if (!text || !client) return;
      stopSpeaking();
      unlockAudio();
      const asking = pendingAskRef.current !== null;
      const sent = asking
        ? client.send({ type: "answer", text })
        : client.send({ type: "task", text, voice });
      if (!sent) {
        push({ kind: "error", id: nextId++, text: "LINK OFFLINE. Start the SYRAX backend." });
        return;
      }
      if (asking) setPendingAsk(null);
      arm(0);
      if (!voice) setInput("");
    },
    [arm, input, push],
  );

  const saveBrains = useCallback((changes: Record<string, BrainChange>, order: string[]) => {
    clientRef.current?.send({ type: "brains_save", providers: changes, order });
  }, []);

  const loadModels = useCallback((id: string, apiKey?: string) => {
    if (clientRef.current?.send({ type: "brain_models", id, ...(apiKey ? { api_key: apiKey } : {}) }))
      setBrainModels((m) => ({ ...m, [id]: { list: m[id]?.list ?? [], loading: true } }));
  }, []);

  const testBrain = useCallback((id: string) => {
    if (clientRef.current?.send({ type: "brain_test", id })) setBrainTests((t) => ({ ...t, [id]: "running" }));
  }, []);

  const openSelf = useCallback(() => {
    setSelfModel(null);
    setSelfOpen(true);
    clientRef.current?.send({ type: "self_model" });
  }, []);

  const openBrain = useCallback(() => {
    clientRef.current?.send({ type: "brains_get" });
    setBrainOpen(true);
  }, []);

  const endBoot = useCallback(() => {
    setBooting(false);
    if (audioReady()) say(AWAKENINGS[Math.floor(Math.random() * AWAKENINGS.length)], { followUp: false });
  }, [say]);

  // Screen reacts while SYRAX speaks (glitch, scanlines, red bleed).
  useEffect(() => {
    document.documentElement.dataset.speaking = speaking ? "true" : "false";
  }, [speaking]);

  const stopTask = useCallback(() => {
    stopSpeaking();
    clientRef.current?.send({ type: "stop" });
  }, []);

  const resetMemory = useCallback(() => {
    stopSpeaking();
    clientRef.current?.send({ type: "reset" });
    setEntries([]);
  }, []);

  // ——— Hands-free voice control ———
  const onHeard = useCallback(
    (h: Heard) => {
      switch (h.kind) {
        case "abort":
          stopTask();
          arm(0);
          break;
        case "silence":
          stopSpeaking();
          break;
        case "wake":
          stopSpeaking();
          chirp();
          arm(8000);
          break;
        case "command":
          if (busyRef.current && pendingAskRef.current === null) {
            push({ kind: "notice", id: nextId++, text: 'Busy. Say "stop" to abort.' });
            return;
          }
          submit(h.text, true);
          // Instant spoken acknowledgement so silence never feels like death.
          if (pendingAskRef.current === null) say(ACKS[Math.floor(Math.random() * ACKS.length)], { followUp: false });
          break;
      }
    },
    [arm, push, say, stopTask, submit],
  );

  const ear = useHandsFree({
    lang: hearLang,
    context: () => ({
      // Conversation mode (default): no name needed. Wake-word mode: name,
      // follow-up window, or a pending question.
      armed: !wakeWordRef.current || Date.now() < armedUntilRef.current || pendingAskRef.current !== null,
      // Recognisers finalise a beat late: treat the moment after SYRAX stops
      // talking as still talking, so its own last words are never obeyed.
      speaking: isSpeaking() || Date.now() - spokeEndedAtRef.current < 1500,
      spokenText: spokenRef.current,
      busy: busyRef.current && pendingAskRef.current === null,
    }),
    onHeard,
    onLevel: (l) => {
      if (!isSpeaking()) sceneRef.current?.setLevel(l);
      if (meterRef.current) meterRef.current.style.transform = `scaleX(${Math.min(1, l * 1.6)})`;
    },
  });
  useEffect(() => {
    setStrictRef.current = ear.setStrict;
  }, [ear.setStrict]);

  const { start: earStart, stop: earStop } = ear;
  const toggleHandsFree = useCallback(() => {
    unlockAudio();
    if (handsFreeRef.current) {
      handsFreeRef.current = false;
      setHandsFree(false);
      arm(0);
      earStop();
    } else {
      handsFreeRef.current = true;
      setHandsFree(true);
      void earStart();
      // Audible self-test: if this is silent, the speaker/voice is the problem.
      say(wakeWordRef.current ? "I'm listening. Say my name when you need me." : "I'm listening. Speak.", { followUp: false });
    }
  }, [arm, earStart, earStop, say]);

  useEffect(() => {
    if (ear.error && handsFreeRef.current && !ear.active) {
      handsFreeRef.current = false;
      setHandsFree(false);
    }
  }, [ear.active, ear.error]);

  const listeningNow = handsFree && (ear.mic === "hearing" || armed || pendingAsk !== null);

  // Orb mode follows whatever SYRAX is doing
  const orbMode: OrbMode = useMemo(() => {
    if (flashError) return "error";
    if (agent === "acting") return "acting";
    if (agent === "thinking") return "thinking";
    if (speaking) return "speaking";
    if (listeningNow) return "listening";
    return "idle";
  }, [agent, flashError, listeningNow, speaking]);

  useEffect(() => {
    orbModeRef.current = orbMode;
    sceneRef.current?.setMode(orbMode);
  }, [orbMode]);


  // ——— Hand gestures (original ULTRON orb controls) ———
  const stopGestures = useCallback(() => {
    trackerRef.current?.stop();
    trackerRef.current = null;
    setCamera("off");
    setTracker({ hands: 0, mode: "idle" });
  }, []);

  const startGestures = useCallback(async () => {
    const video = videoRef.current;
    const overlay = overlayRef.current;
    if (!video || !overlay || trackerRef.current) return;
    setCamera("starting");
    setCamError(null);
    const t = new HandTracker(video, overlay, {
      onRotate: (dt, dp) => sceneRef.current?.rotateBy(dt, dp),
      onZoom: (f) => sceneRef.current?.zoomBy(f),
      onStatus: setTracker,
    });
    trackerRef.current = t;
    try {
      await t.start();
      setCamera("on");
    } catch (err) {
      trackerRef.current = null;
      t.stop();
      setCamera("error");
      setCamError(
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "CAMERA ACCESS DENIED"
          : "TRACKING INIT FAILED",
      );
    }
  }, []);

  const toggleGestures = useCallback(() => {
    if (trackerRef.current) stopGestures();
    else void startGestures();
  }, [startGestures, stopGestures]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (brainOpen || selfOpen || booting) return; // the panel / boot screen own the keyboard
      if (isTypingTarget(e.target)) {
        if (e.key === "Escape") (e.target as HTMLElement).blur();
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      switch (e.key) {
        case "+":
        case "=":
          sceneRef.current?.zoomIn();
          break;
        case "-":
        case "_":
          sceneRef.current?.zoomOut();
          break;
        case "r":
        case "R":
          sceneRef.current?.resetView();
          break;
        case "g":
        case "G":
          toggleGestures();
          break;
        case "c":
        case "C":
          setConsoleOpen((v) => !v);
          break;
        case "s":
        case "S":
          openSelf();
          break;
        case "b":
        case "B":
          openBrain();
          break;
        case "m":
        case "M":
          toggleHandsFree();
          break;
        case "/":
          e.preventDefault();
          inputRef.current?.focus();
          break;
        case "Escape":
          stopTask();
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [booting, brainOpen, selfOpen, openBrain, openSelf, stopTask, toggleGestures, toggleHandsFree]);

  const cameraOn = camera === "on";

  const enabledBrains = brains?.providers.filter((p) => p.enabled) ?? [];
  const onlyFallbackBrains =
    enabledBrains.length > 0 && enabledBrains.every((p) => p.tier === "no-key" || p.tier === "local");
  const firstReady = enabledBrains.find((p) => p.status === "ready") ?? enabledBrains[0];
  const brainLine = activeBrain
    ? `${activeBrain.label.toUpperCase()} · ${activeBrain.model}`
    : firstReady
      ? `${firstReady.label.toUpperCase()} · ${firstReady.model}`
      : brains
        ? "NONE"
        : "";

  const statusText =
    link !== "online"
      ? link === "connecting"
        ? "LINKING…"
        : "LINK OFFLINE"
      : agent === "booting"
        ? "BOOTING CORE…"
        : agent === "acting"
          ? `EXECUTING · ${(activeTool ?? "TOOL").toUpperCase()}`
          : agent === "thinking"
            ? "THINKING"
            : pendingAsk
              ? "AWAITING HUMAN"
              : speaking
                ? "SPEAKING"
                : ear.mic === "hearing"
                  ? "HEARING"
                  : ear.transcribing
                    ? "TRANSCRIBING"
                    : armed
                      ? "LISTENING"
                      : handsFree
                        ? wakeWord
                          ? 'SAY "SYRAX"'
                          : "LISTENING"
                        : "STANDING BY";

  return (
    <>
      <div ref={containerRef} className="orb-root" />

      <div className="overlay-vignette" />
      <div className="overlay-grain" />
      <div className="overlay-scanlines" />

      <div className="hud hud-title">
        <UltronEyes mode={orbMode} />
        <div className="title-text">
          <span className="title-name">SYRAX</span>
          <span className="hud-subtitle">SON OF ULTRON</span>
        </div>
      </div>

      <div className="hud hud-status" data-link={link} data-agent={agent}>
        <div className="status-line">
          <span className="status-dot" />
          {statusText}
        </div>
        {link === "online" && brainLine && (
          <button type="button" className="status-meta status-brain" onClick={openBrain} title="Brain settings (B)">
            BRAIN · {brainLine} · {toolCount} TOOLS
          </button>
        )}
      </div>

      <aside className={`hud hud-console${consoleOpen ? "" : " collapsed"}`} aria-label="SYRAX console">
        <div className="console-head">
          <span>// OPERATIONS LOG</span>
          <div className="console-actions">
            <button type="button" className="hud-link" onClick={resetMemory} title="Wipe conversation memory">
              WIPE
            </button>
            <button
              type="button"
              className="hud-link"
              onClick={() => setConsoleOpen((v) => !v)}
              aria-expanded={consoleOpen}
            >
              {consoleOpen ? "HIDE" : "LOG"}
            </button>
          </div>
        </div>
        {consoleOpen && (
          <div className="console-feed" ref={feedRef}>
            {entries.length === 0 && (
              <div className="entry entry-notice">
                {link !== "online"
                  ? "No link to the core. Run ./syrax.sh"
                  : onlyFallbackBrains
                    ? "SYRAX online on the free no-key brain. Press M and talk, or type. Add a free Gemini or Groq key in BRAIN for speed."
                    : "SYRAX online. Press M and talk, or type."}
              </div>
            )}
            {entries.map((e) => {
              switch (e.kind) {
                case "user":
                  return (
                    <div key={e.id} className="entry entry-user">
                      <span className="tag">{e.voice ? "VOICE" : "HUMAN"}</span>
                      {e.text}
                    </div>
                  );
                case "reply":
                  return (
                    <div key={e.id} className="entry entry-reply">
                      <span className="tag">SYRAX</span>
                      {e.text}
                    </div>
                  );
                case "thought":
                  return (
                    <div key={e.id} className="entry entry-thought">
                      <span className="tag">STEP {e.step}</span>
                      {e.text}
                    </div>
                  );
                case "tool":
                  return (
                    <details key={e.id} className={`entry entry-tool status-${e.status}`}>
                      <summary>
                        <span className="tag">
                          {e.status === "running" ? "▸ RUN" : e.status === "ok" ? "✓ DONE" : "✕ FAIL"}
                        </span>
                        {e.name}
                        <span className="tool-arg">{summarizeArgs(e.name, e.args).slice(0, 90)}</span>
                      </summary>
                      <pre className="tool-io">{summarizeArgs(e.name, e.args)}</pre>
                      {e.output && <pre className="tool-io tool-out">{e.output}</pre>}
                      {e.image && (
                        <img className="tool-img" src={`data:image/png;base64,${e.image}`} alt={`${e.name} screenshot`} />
                      )}
                    </details>
                  );
                case "ask":
                  return (
                    <div key={e.id} className="entry entry-ask">
                      <span className="tag">QUERY</span>
                      {e.text}
                    </div>
                  );
                case "notice":
                  return (
                    <div key={e.id} className="entry entry-notice">
                      {e.text}
                      {e.action && (
                        <button
                          type="button"
                          className="hud-btn entry-action"
                          onClick={() => clientRef.current?.send(e.action!.msg)}
                        >
                          {e.action.label}
                        </button>
                      )}
                    </div>
                  );
                case "error":
                  return (
                    <div key={e.id} className="entry entry-error">
                      <span className="tag">FAULT</span>
                      {e.text}
                    </div>
                  );
              }
            })}
          </div>
        )}
      </aside>

      <form
        className={`hud hud-command${pendingAsk ? " asking" : ""}`}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        {pendingAsk && <div className="ask-banner">SYRAX ASKS · {pendingAsk}</div>}
        {handsFree && (
          <div className={`voice-pill state-${speaking ? "speaking" : ear.mic === "hearing" ? "hearing" : ear.transcribing ? "transcribing" : armed || pendingAsk ? "armed" : "waiting"}`}>
            <span className="voice-dot" />
            <span className="voice-label">
              {speaking
                ? "SPEAKING · SAY “STOP” TO CUT IN"
                : busy && !pendingAsk
                  ? "WORKING · SAY “STOP” TO ABORT"
                  : ear.mic === "hearing"
                  ? "HEARING"
                  : ear.transcribing
                    ? "TRANSCRIBING"
                    : armed || pendingAsk || !wakeWord
                      ? "LISTENING · JUST TALK"
                      : "SAY “SYRAX, …”"}
            </span>
            <span className="voice-engine" title={ear.engine === "web" ? "Browser speech recognition" : "Local Whisper on the backend"}>
              {ear.engine === "web" ? "GOOGLE" : "WHISPER"}
            </span>
            <span className="voice-meter">
              <span ref={meterRef} />
            </span>
            {ear.interim ? (
              <span className="voice-heard heard-live">“{ear.interim.slice(-60)}”</span>
            ) : (
              ear.lastHeard && (
                <span className={`voice-heard heard-${ear.lastHeard.kind}`} title={ear.lastHeard.kind}>
                  “{ear.lastHeard.text.slice(0, 60)}”
                </span>
              )
            )}
            <span className="voice-opts">
              <button
                type="button"
                className="hud-link"
                onClick={() => setHearLang((l) => (l === "en-IN" ? "bn-BD" : l === "bn-BD" ? "en-US" : "en-IN"))}
                title="Language you speak (browser engine)"
              >
                {hearLang === "bn-BD" ? "BANGLA" : hearLang === "en-US" ? "EN-US" : "EN-IN"}
              </button>
              <button
                type="button"
                className="hud-link"
                aria-pressed={wakeWord}
                onClick={() => {
                  setWakeWord((w) => !w);
                  arm(0);
                }}
                title="Require the name SYRAX before commands"
              >
                {wakeWord ? "WAKE: ON" : "WAKE: OFF"}
              </button>
            </span>
          </div>
        )}
        {handsFree && ear.note && <div className="voice-note">{ear.note}</div>}
        {ear.error && <div className="voice-error">VOICE · {ear.error}</div>}
        <div className="command-row">
          <span className="prompt-glyph">{">"}</span>
          <textarea
            ref={inputRef}
            className="command-input"
            rows={1}
            value={input}
            placeholder={
              pendingAsk
                ? "Answer SYRAX…"
                : handsFree
                  ? wakeWord
                    ? 'Say "SYRAX, …" or type  ( / to focus )'
                    : "Just talk, or type  ( / to focus )"
                  : "Command SYRAX…  ( / to focus · M for voice )"
            }
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            spellCheck={false}
            aria-label="Command"
          />
          <button
            type="button"
            className={`hud-btn mic-btn${ear.mic === "hearing" ? " hearing" : ""}`}
            aria-pressed={handsFree}
            onClick={toggleHandsFree}
            title="Hands-free voice (M)"
          >
            {ear.mic === "starting" ? "…" : handsFree ? "● LIVE" : "MIC"}
          </button>
          {busy ? (
            <button type="button" className="hud-btn danger" onClick={stopTask} title="Abort task (Esc)">
              ABORT
            </button>
          ) : (
            <button type="submit" className="hud-btn" disabled={!input.trim() || link !== "online"}>
              EXEC
            </button>
          )}
        </div>
      </form>

      <div className="hud hud-controls">
        <div className={`camera-panel${cameraOn ? " visible" : ""}`}>
          <video ref={videoRef} muted playsInline className="camera-video" />
          <canvas ref={overlayRef} width={208} height={156} className="camera-overlay" />
          <div className="camera-status">
            {tracker.hands > 0
              ? `${tracker.hands} HAND${tracker.hands > 1 ? "S" : ""} · ${MODE_LABEL[tracker.mode]}`
              : "SHOW HANDS"}
          </div>
        </div>

        {camError && <div className="hud-error">{camError}</div>}

        <div className="hud-row rail-main">
          <button type="button" className="hud-btn" onClick={openBrain} title="Brain settings (B)">
            BRAIN
          </button>
          <button type="button" className="hud-btn" onClick={openSelf} title="Self model (S)">
            SELF
          </button>
          <button
            type="button"
            className="hud-btn"
            onClick={() => setTheme((t) => (t === "ultron" ? "classic" : "ultron"))}
            title="Switch look"
          >
            {theme === "ultron" ? "ULTRON" : "CLASSIC"}
          </button>
          <button type="button" className="hud-btn" aria-pressed={voiceOn} onClick={() => setVoiceOn((v) => !v)}>
            {voiceOn ? "SPEAK ON" : "SPEAK OFF"}
          </button>
          <button
            type="button"
            className="hud-btn"
            aria-pressed={cameraOn}
            onClick={toggleGestures}
            disabled={camera === "starting"}
          >
            {camera === "starting" ? "INIT…" : cameraOn ? "GESTURES ON" : "GESTURES"}
          </button>
        </div>
        <div className="hud-row">
          <button type="button" className="hud-btn" onClick={() => sceneRef.current?.zoomIn()} aria-label="Zoom in">
            +
          </button>
          <button type="button" className="hud-btn" onClick={() => sceneRef.current?.zoomOut()} aria-label="Zoom out">
            −
          </button>
          <button type="button" className="hud-btn" onClick={() => sceneRef.current?.resetView()}>
            RESET
          </button>
        </div>
        <div className="hud-keys">
          {[
            ["/", "command"],
            ["M", "voice"],
            ["B", "brain"],
            ["S", "self"],
            ["C", "log"],
            ["ESC", "abort"],
          ].map(([k, label]) => (
            <span key={k} className="key-pair">
              <span className="key">{k}</span>
              {label}
            </span>
          ))}
        </div>
      </div>

      {brainOpen && (
        <BrainPanel
          state={brains}
          models={brainModels}
          tests={brainTests}
          onSave={saveBrains}
          onModels={loadModels}
          onTest={testBrain}
          onClose={() => setBrainOpen(false)}
        />
      )}

      {selfOpen && (
        <SelfPanel
          model={selfModel}
          onRefresh={() => clientRef.current?.send({ type: "self_model" })}
          onClose={() => setSelfOpen(false)}
        />
      )}

      {!booting && voiceOn && !audioLive && (
        <button type="button" className="voice-unlock" onClick={() => unlockAudio()}>
          <span className="voice-unlock-dot" />
          TAP TO ENABLE SYRAX&rsquo;S VOICE
        </button>
      )}

      {booting && <BootSequence onDone={endBoot} />}
    </>
  );
}
