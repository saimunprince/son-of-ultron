"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { mapDevices, micConstraints, pickDevice, speakerChoiceSupported, type AudioPrefs, type DeviceList } from "@/lib/audioDevices";
import { keyLabel, pttKeyAllowed } from "@/lib/pushToTalk";

interface Props {
  prefs: AudioPrefs;
  /** false: the browser did not keep it (no storage), it still holds for this visit */
  saved: boolean;
  onChange: (prefs: AudioPrefs) => void;
  onClose: () => void;
}

const EMPTY: DeviceList = { options: [{ id: "", label: "System default" }], needsPermission: false };

/** 0.5 s two-note chime as WAV, so the speaker test plays through an <audio> element and its setSinkId. */
function chimeWav(): Blob {
  const rate = 24000;
  const n = Math.round(rate * 0.5);
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF");
  v.setUint32(4, 36 + n * 2, true);
  str(8, "WAVEfmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, "data");
  v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const t = i / rate;
    const f = t < 0.22 ? 660 : 990;
    const env = Math.min(1, t * 60) * Math.min(1, (0.5 - t) * 12);
    v.setInt16(44 + i * 2, Math.sin(2 * Math.PI * f * t) * env * 0.3 * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

/** Microphone, speaker and push-to-talk key. Changes apply at once and are kept per browser. */
export default function AudioPanel({ prefs, saved, onChange, onClose }: Props) {
  const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
  const [mics, setMics] = useState<DeviceList>(EMPTY);
  const [speakers, setSpeakers] = useState<DeviceList>(EMPTY);
  const [testing, setTesting] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [speakerNote, setSpeakerNote] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [sinkOk] = useState(speakerChoiceSupported);
  const meterRef = useRef<HTMLSpanElement>(null);
  const meterBoxRef = useRef<HTMLDivElement>(null);
  const testRef = useRef<{ stop: () => void } | null>(null);

  const refresh = useCallback(async () => {
    if (!md?.enumerateDevices) return;
    try {
      const all = await md.enumerateDevices();
      setMics(mapDevices(all, "audioinput"));
      setSpeakers(mapDevices(all, "audiooutput"));
    } catch {
      /* the list stays as it was */
    }
  }, [md]);

  useEffect(() => {
    void refresh();
    md?.addEventListener?.("devicechange", refresh);
    return () => md?.removeEventListener?.("devicechange", refresh);
  }, [md, refresh]);

  const stopTest = useCallback(() => {
    testRef.current?.stop();
    testRef.current = null;
    setTesting(false);
  }, []);

  const startTest = useCallback(
    async (micId: string) => {
      testRef.current?.stop();
      testRef.current = null;
      setMicError(null);
      if (!md?.getUserMedia) {
        setMicError("This page cannot open the microphone (it needs https or localhost).");
        return;
      }
      let stream: MediaStream;
      try {
        stream = await md.getUserMedia({ audio: micConstraints(micId) });
      } catch (e) {
        setMicError(e instanceof DOMException && e.name === "NotAllowedError" ? "Microphone access was refused." : "The microphone did not open.");
        setTesting(false);
        return;
      }
      void refresh(); // with permission the devices have their names
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      ctx.createMediaStreamSource(stream).connect(analyser); // never to the speakers
      const samples = new Float32Array(analyser.fftSize);
      let raf = 0;
      let lastAria = 0;
      const tick = (now: number) => {
        analyser.getFloatTimeDomainData(samples);
        let sum = 0;
        for (const s of samples) sum += s * s;
        const level = Math.min(1, Math.sqrt(sum / samples.length) * 12);
        if (meterRef.current) meterRef.current.style.transform = `scaleX(${level})`;
        if (meterBoxRef.current && now - lastAria > 500) {
          lastAria = now;
          meterBoxRef.current.setAttribute("aria-valuenow", String(Math.round(level * 100)));
        }
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
      testRef.current = {
        stop: () => {
          cancelAnimationFrame(raf);
          stream.getTracks().forEach((t) => t.stop());
          void ctx.close().catch(() => {});
          if (meterRef.current) meterRef.current.style.transform = "scaleX(0)";
        },
      };
      setTesting(true);
    },
    [md, refresh],
  );

  useEffect(() => () => testRef.current?.stop(), []);

  const testSpeaker = async () => {
    setSpeakerNote(null);
    const url = URL.createObjectURL(chimeWav());
    const el = new Audio(url) as HTMLAudioElement & { setSinkId?: (id: string) => Promise<void> };
    el.onended = () => URL.revokeObjectURL(url);
    try {
      if (prefs.speakerId && el.setSinkId) await el.setSinkId(prefs.speakerId);
      await el.play();
    } catch (e) {
      URL.revokeObjectURL(url);
      setSpeakerNote(`The test sound did not play: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (capturing) {
        e.preventDefault();
        e.stopPropagation();
        if (e.code === "Escape") {
          setCapturing(false);
          setKeyError(null);
          return;
        }
        if (!pttKeyAllowed(e.code)) {
          setKeyError(`${keyLabel(e.code || e.key)} is taken by another shortcut. Try another key.`);
          return;
        }
        setCapturing(false);
        setKeyError(null);
        onChange({ ...prefs, pttKey: e.code });
        return;
      }
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [capturing, onChange, onClose, prefs]);

  const micValue = pickDevice(mics.options, prefs.micId);
  const speakerValue = pickDevice(speakers.options, prefs.speakerId);

  return (
    <div className="brain-backdrop" onClick={onClose}>
      <div className="brain-panel audio-panel" role="dialog" aria-modal="true" aria-labelledby="audio-title" onClick={(e) => e.stopPropagation()}>
        <div className="brain-head">
          <span id="audio-title">// AUDIO DEVICES</span>
          <button type="button" className="hud-link" onClick={onClose}>
            CLOSE
          </button>
        </div>
        <p className="brain-intro">
          Choose the microphone SYRAX listens on and the speaker it talks through. The choice is kept in this browser
          {saved ? "." : " for this visit only (the browser does not allow storage here)."}
        </p>

        <div className="brain-list audio-body">
          {!md && <div className="brain-error">Device choice needs a secure page (https or localhost).</div>}

          <div className="brain-field">
            <label htmlFor="audio-mic">MICROPHONE</label>
            <div className="brain-inline">
              <select
                id="audio-mic"
                autoFocus
                value={micValue}
                onChange={(e) => {
                  onChange({ ...prefs, micId: e.target.value });
                  if (testing) void startTest(e.target.value);
                }}
              >
                {mics.options.map((o) => (
                  <option key={o.id || "default"} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="hud-btn"
                aria-pressed={testing}
                onClick={() => (testing ? stopTest() : void startTest(micValue))}
              >
                {testing ? "STOP TEST" : "TEST"}
              </button>
            </div>
            <div
              ref={meterBoxRef}
              className="voice-meter audio-meter"
              role="meter"
              aria-label="Microphone input level"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={0}
            >
              <span ref={meterRef} />
            </div>
            {mics.needsPermission && (
              <div className="brain-note">Device names appear once the microphone is allowed: press TEST.</div>
            )}
            {micError && (
              <div className="brain-error" role="alert">
                {micError}
              </div>
            )}
          </div>

          <div className="brain-field">
            <label htmlFor={sinkOk ? "audio-speaker" : undefined}>SPEAKER</label>
            {sinkOk ? (
              <>
                <div className="brain-inline">
                  <select id="audio-speaker" value={speakerValue} onChange={(e) => onChange({ ...prefs, speakerId: e.target.value })}>
                    {speakers.options.map((o) => (
                      <option key={o.id || "default"} value={o.id}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="hud-btn" onClick={() => void testSpeaker()}>
                    TEST
                  </button>
                </div>
                {speakerNote && (
                  <div className="brain-error" role="alert">
                    {speakerNote}
                  </div>
                )}
              </>
            ) : (
              <div className="brain-note">This browser plays SYRAX through the system&rsquo;s default speaker (choosing one needs Chrome or Edge).</div>
            )}
          </div>

          <div className="brain-field">
            <span className="audio-label" id="audio-ptt-label">
              PUSH-TO-TALK KEY
            </span>
            <div className="brain-inline" role="group" aria-labelledby="audio-ptt-label">
              <span className="key" aria-label={`Current key: ${keyLabel(prefs.pttKey)}`}>
                {keyLabel(prefs.pttKey)}
              </span>
              <button type="button" className="hud-btn" aria-pressed={capturing} onClick={() => setCapturing((c) => !c)}>
                {capturing ? "PRESS A KEY… (ESC CANCELS)" : "CHANGE"}
              </button>
              {prefs.pttKey !== "Space" && (
                <button type="button" className="hud-link" onClick={() => onChange({ ...prefs, pttKey: "Space" })}>
                  RESET TO SPACE
                </button>
              )}
            </div>
            <div className="brain-note">
              Hold the key to talk, release to send. It never fires while you type in a field
              {prefs.pttKey === "Space" ? "; Space also stays with a focused button, so pick another key (e.g. F2) to talk from anywhere" : ""}.
            </div>
            {keyError && (
              <div className="brain-error" role="alert">
                {keyError}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
