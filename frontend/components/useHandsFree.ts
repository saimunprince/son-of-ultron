"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MicListener, type MicState } from "@/lib/mic";
import { API_BASE } from "@/lib/syraxClient";
import { duck, isSpeaking } from "@/lib/speech";
import { interpret, type Heard, type HeardContext } from "@/lib/wake";
import { WebSpeechEar, webSpeechAvailable } from "@/lib/webSpeech";

export type EarEngine = "web" | "whisper";

interface Options {
  /** current context for deciding what an utterance means */
  context: () => HeardContext;
  onHeard: (h: Heard, transcript: string) => void;
  onLevel?: (level: number) => void;
  /** recognition language for the browser engine, e.g. "en-IN" or "bn-BD" */
  lang: string;
}

/**
 * Always-on listening.
 * - "web": Chrome/Edge speech recognition (fast, accent-robust, live text).
 * - "whisper": browser VAD + backend Whisper, used when "web" is unavailable.
 * The mic stream always runs too, for the level meter and orb.
 */
export function useHandsFree({ context, onHeard, onLevel, lang }: Options) {
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

  const ctxRef = useRef(context);
  const heardRef = useRef(onHeard);
  const levelRef = useRef(onLevel);
  const langRef = useRef(lang);
  useEffect(() => {
    ctxRef.current = context;
    heardRef.current = onHeard;
    levelRef.current = onLevel;
  });

  const deliver = useCallback((text: string) => {
    const heard = interpret(text || "", ctxRef.current());
    if (text) setLastHeard({ text, kind: heard.kind });
    heardRef.current(heard, text || "");
  }, []);

  const handleUtterance = useCallback(
    async (wav: Blob) => {
      setTranscribing((n) => n + 1);
      try {
        const res = await fetch(`${API_BASE}/stt`, { method: "POST", headers: { "content-type": "audio/wav" }, body: wav });
        if (!res.ok) throw new Error(`speech recognition failed (${res.status})`);
        const { text } = (await res.json()) as { text: string };
        deliver(text);
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
    const ear = new WebSpeechEar({
      onFinal: (t) => {
        webAliveAtRef.current = Date.now();
        setInterim("");
        duck(false);
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

  const start = useCallback(async () => {
    if (micRef.current) return;
    const m = new MicListener({
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
      return;
    }
    if (webSpeechAvailable() && !webFailedRef.current) startWeb();
    else switchToWhisper(webSpeechAvailable() ? undefined : "not supported in this browser");
  }, [handleUtterance, startWeb, switchToWhisper]);


  const stop = useCallback(() => {
    webRef.current?.stop();
    webRef.current = null;
    micRef.current?.stop();
    micRef.current = null;
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
      active: mic !== "off" && mic !== "error",
    }),
    [mic, engine, interim, transcribing, lastHeard, error, note, start, stop, setStrict],
  );
}
