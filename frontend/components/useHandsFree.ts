"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MicListener, type MicState } from "@/lib/mic";
import { API_BASE } from "@/lib/syraxClient";
import { duck, isSpeaking } from "@/lib/speech";
import { interpret, type Heard, type HeardContext } from "@/lib/wake";
import { WebSpeechEar, webSpeechAvailable } from "@/lib/webSpeech";
import { micConstraints } from "@/lib/audioDevices";

export type EarEngine = "web" | "whisper";

interface Options {
  /** current context for deciding what an utterance means */
  context: () => HeardContext;
  onHeard: (h: Heard, transcript: string) => void;
  onLevel?: (level: number) => void;
  /** recognition language for the browser engine, e.g. "en-IN" or "bn-BD" */
  lang: string;
  /** the chosen microphone ("" = system default), used from the next mic start */
  micId?: string;
}

/**
 * Always-on listening.
 * - "web": Chrome/Edge speech recognition (fast, accent-robust, live text).
 * - "whisper": browser VAD + backend Whisper, used when "web" is unavailable.
 * The mic stream always runs too, for the level meter and orb.
 */
export function useHandsFree({ context, onHeard, onLevel, lang, micId = "" }: Options) {
  const micRef = useRef<MicListener | null>(null);
  const webRef = useRef<WebSpeechEar | null>(null);
  const webFailedRef = useRef(false);
  const engineRef = useRef<EarEngine>("whisper");
  // Watchdog: the browser engine can be present yet deaf (e.g. Chromium
  // without Google keys). The VAD keeps running in parallel; if it hears
  // speech and the browser engine reports nothing, fall back to Whisper and
  // transcribe that same utterance so the command is not lost.
  const webAliveAtRef = useRef(0);
  const speechStartAtRef = useRef(0);
  const [mic, setMic] = useState<MicState>("off");
  const [engine, setEngine] = useState<EarEngine>("whisper");
  const [transcribing, setTranscribing] = useState(0);
  const [interim, setInterim] = useState("");
  const [lastHeard, setLastHeard] = useState<{ text: string; kind: Heard["kind"] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // Push-to-talk (2026-11-26): the held key records through the same MicListener and sends to /stt on release.
  const [ptt, setPtt] = useState(false);
  const pttRef = useRef(false);
  /** the mic was off: push-to-talk opened it and closes it again on release */
  const pttOwnsMicRef = useRef(false);
  /** the browser engine hears the held words too: its results are dropped until then, Whisper's one counts */
  const muteWebUntilRef = useRef(0);
  const micIdRef = useRef(micId);
  micIdRef.current = micId;

  const ctxRef = useRef(context);
  const heardRef = useRef(onHeard);
  const levelRef = useRef(onLevel);
  const langRef = useRef(lang);
  useEffect(() => {
    ctxRef.current = context;
    heardRef.current = onHeard;
    levelRef.current = onLevel;
  });

  const deliver = useCallback((text: string, pushed = false) => {
    const ctx = ctxRef.current();
    // a held push-to-talk key is the human addressing SYRAX: no wake word, and not mistaken for SYRAX's own voice
    const heard = interpret(text || "", pushed ? { ...ctx, armed: true, speaking: false } : ctx);
    if (text) setLastHeard({ text, kind: heard.kind });
    heardRef.current(heard, text || "");
  }, []);

  const handleUtterance = useCallback(
    async (wav: Blob, pushed = false) => {
      setTranscribing((n) => n + 1);
      try {
        const res = await fetch(`${API_BASE}/stt`, { method: "POST", headers: { "content-type": "audio/wav" }, body: wav });
        if (!res.ok) throw new Error(`speech recognition failed (${res.status})`);
        const { text } = (await res.json()) as { text: string };
        deliver(text, pushed);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        duck(false);
        setTranscribing((n) => Math.max(0, n - 1));
      }
    },
    [deliver],
  );

  const switchToWhisper = useCallback((why?: string) => {
    webRef.current?.stop();
    webRef.current = null;
    webFailedRef.current = true;
    engineRef.current = "whisper";
    setEngine("whisper");
    setInterim("");
    if (why) setNote(`Browser speech unavailable (${why}). Using local Whisper, English only.`);
  }, []);

  const startWeb = useCallback(() => {
    webRef.current?.stop(); // a language switch: the old recognizer would keep restarting itself
    const ear = new WebSpeechEar({
      onFinal: (t) => {
        webAliveAtRef.current = Date.now();
        setInterim("");
        duck(false);
        if (pttRef.current || Date.now() < muteWebUntilRef.current) return; // push-to-talk sends these words itself
        deliver(t);
      },
      onInterim: (t) => {
        if (t) webAliveAtRef.current = Date.now();
        setInterim(t);
      },
      onSpeechStart: () => {
        if (isSpeaking()) duck(true);
      },
      onUnavailable: (why) => switchToWhisper(why),
      onDenied: () => setError("MIC ACCESS DENIED"),
    });
    webRef.current = ear;
    engineRef.current = "web";
    setEngine("web");
    setNote(null);
    ear.start(langRef.current);
  }, [deliver, switchToWhisper]);

  /** Open the mic; withWeb=false (push-to-talk alone) skips the browser engine. True when the mic runs. */
  const openMic = useCallback(async (withWeb: boolean): Promise<boolean> => {
    if (micRef.current) return true;
    const m = new MicListener({
      constraints: () => micConstraints(micIdRef.current),
      onUtterance: (wav) => {
        if (engineRef.current === "whisper") {
          void handleUtterance(wav);
          return;
        }
        const startedAt = speechStartAtRef.current;
        setTimeout(() => {
          if (engineRef.current === "web" && webAliveAtRef.current < startedAt) {
            switchToWhisper("browser speech is not responding");
            void handleUtterance(wav);
          }
        }, 3500);
      },
      onSpeechStart: () => {
        speechStartAtRef.current = Date.now();
        if (isSpeaking()) duck(true); // human talks over SYRAX: lower its voice at once
      },
      onLevel: (l) => levelRef.current?.(l),
      onState: setMic,
    });
    micRef.current = m;
    try {
      await m.start();
      if (micRef.current !== m) {
        m.stop(); // hands-free went off while the mic was starting: nothing may keep listening
        return false;
      }
      setError(null);
    } catch (e) {
      micRef.current = null;
      setError(
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "MIC ACCESS DENIED"
          : e instanceof Error
            ? e.message
            : "MIC FAILED",
      );
      return false;
    }
    if (!withWeb) return true;
    if (webSpeechAvailable() && !webFailedRef.current) startWeb();
    else switchToWhisper(webSpeechAvailable() ? undefined : "not supported in this browser");
    return true;
  }, [handleUtterance, startWeb, switchToWhisper]);

  const start = useCallback(async () => {
    if (micRef.current) {
      // push-to-talk had the mic open on its own: hands-free takes it over and adds the browser engine
      if (pttOwnsMicRef.current) {
        pttOwnsMicRef.current = false;
        if (webSpeechAvailable() && !webFailedRef.current) startWeb();
      }
      return;
    }
    await openMic(true);
  }, [openMic, startWeb]);

  /** Close the mic that push-to-talk opened on its own (hands-free was off). */
  const closePttMic = useCallback(() => {
    pttOwnsMicRef.current = false;
    micRef.current?.stop();
    micRef.current = null;
  }, []);

  /** Push-to-talk pressed: record everything until pttUp(). */
  const pttDown = useCallback(async () => {
    if (pttRef.current) return;
    pttRef.current = true;
    setPtt(true);
    muteWebUntilRef.current = Number.POSITIVE_INFINITY;
    setInterim("");
    if (!micRef.current) {
      pttOwnsMicRef.current = true;
      const ok = await openMic(false);
      if (!ok) {
        pttOwnsMicRef.current = false;
        pttRef.current = false;
        setPtt(false);
        muteWebUntilRef.current = 0;
        return;
      }
      if (!pttRef.current) {
        // released while the browser was still opening the mic: nothing was said through it
        if (pttOwnsMicRef.current) closePttMic();
        return;
      }
    }
    micRef.current?.beginManual();
  }, [openMic, closePttMic]);

  /** Push-to-talk released: send what was held to /stt as an addressed command. */
  const pttUp = useCallback(() => {
    if (!pttRef.current) return;
    pttRef.current = false;
    setPtt(false);
    // the browser engine finalises a beat late: keep its copy of these words out
    muteWebUntilRef.current = Date.now() + 2500;
    const wav = micRef.current?.endManual() ?? null;
    if (pttOwnsMicRef.current) closePttMic();
    if (wav) void handleUtterance(wav, true);
  }, [handleUtterance, closePttMic]);


  const stop = useCallback(() => {
    webRef.current?.stop();
    webRef.current = null;
    micRef.current?.stop();
    micRef.current = null;
    pttOwnsMicRef.current = false;
    pttRef.current = false;
    setPtt(false);
    setInterim("");
  }, []);

  // Language switch restarts the browser engine.
  useEffect(() => {
    langRef.current = lang;
    if (webRef.current) startWeb();
  }, [lang, startWeb]);

  /** While SYRAX talks, demand a louder voice before treating it as speech. */
  const setStrict = useCallback((on: boolean) => {
    if (micRef.current) micRef.current.strict = on;
  }, []);

  useEffect(
    () => () => {
      webRef.current?.stop();
      micRef.current?.stop();
    },
    [],
  );

  return useMemo(
    () => ({
      mic,
      engine,
      interim,
      transcribing: transcribing > 0,
      lastHeard,
      error,
      note,
      start,
      stop,
      setStrict,
      ptt,
      pttDown,
      pttUp,
      active: mic !== "off" && mic !== "error",
    }),
    [mic, engine, interim, transcribing, lastHeard, error, note, start, stop, setStrict, ptt, pttDown, pttUp],
  );
}
