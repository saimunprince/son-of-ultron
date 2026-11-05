"use client";

import { useEffect, useState } from "react";
import type { AndroidState } from "@/lib/syraxClient";

interface Props {
  state: AndroidState | null;
  busy: boolean;
  onFind: () => void;
  onPair: (host: string, port: string, code: string) => void;
  onConnect: (host: string, port: string) => void;
  onDisconnect: () => void;
  onRefresh: () => void;
  onClose: () => void;
}

const STATE_LABEL: Record<string, string> = {
  device: "CONNECTED",
  unauthorized: "ALLOW ON PHONE",
  offline: "OFFLINE",
};

/** "192.168.1.7:41235" -> ["192.168.1.7", "41235"]; a bare IP keeps the port field as it is */
function split(address: string): [string, string] | null {
  const m = /^\s*([^\s:]+):(\d{2,5})\s*$/.exec(address);
  return m ? [m[1], m[2]] : null;
}

export default function AndroidPanel({ state, busy, onFind, onPair, onConnect, onDisconnect, onRefresh, onClose }: Props) {
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [pairPort, setPairPort] = useState("");
  const [code, setCode] = useState("");
  const [pairing, setPairing] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // the last phone's IP fills the form once
  const saved = state?.saved ?? null;
  useEffect(() => {
    const parts = saved ? split(saved) : null;
    if (parts) setHost((h) => h || parts[0]);
  }, [saved]);

  // a pasted "ip:port" fills both fields
  const takeHost = (v: string, setP: (p: string) => void) => {
    const parts = split(v);
    if (parts) {
      setHost(parts[0]);
      setP(parts[1]);
    } else setHost(v);
  };

  const ready = state?.devices.filter((d) => d.state === "device") ?? [];
  // 2026-11-05: the owner typed the IP and port and pressed Enter, which did nothing; Enter connects (or pairs) now
  const canConnect = !busy && !!host.trim() && !!port;
  const canPair = !busy && !!host.trim() && !!pairPort && code.length === 6;

  return (
    <div className="brain-backdrop" onClick={onClose}>
      <div className="brain-panel android-panel" role="dialog" aria-label="Android phone" onClick={(e) => e.stopPropagation()}>
        <div className="brain-head">
          <span>// ANDROID LINK</span>
          <button type="button" className="hud-link" onClick={onClose}>
            CLOSE
          </button>
        </div>
        <p className="brain-intro">
          SYRAX uses your phone the way you do: it sees the screen, taps, types and opens apps. Anything that sends a
          message asks you first unless you asked for that send.
        </p>

        {!state ? (
          <div className="brain-empty">Reading the link…</div>
        ) : !state.adb ? (
          <div className="brain-error">{state.message}</div>
        ) : (
          <>
            <ol className="brain-list">
              {state.devices.length === 0 && <li className="brain-empty">No phone connected.</li>}
              {state.devices.map((d) => (
                <li key={d.serial} className={`brain-row ${d.state === "device" ? "status-ready active" : "status-off"}`}>
                  <div className="brain-row-main android-row">
                    <span className="brain-name">
                      {d.model || "Android phone"}
                      <span className="brain-tier">{d.wifi ? "WIFI" : "USB"}</span>
                    </span>
                    <span className="brain-status" title={d.serial}>
                      {STATE_LABEL[d.state] ?? d.state.toUpperCase()}
                    </span>
                  </div>
                </li>
              ))}
            </ol>

            <div className="android-actions">
              <button type="button" className="hud-btn" onClick={onFind} disabled={busy} title="Find a phone with Wireless debugging on, on this WiFi">
                FIND ON WIFI
              </button>
              <button type="button" className="hud-link" onClick={onRefresh} disabled={busy}>
                REFRESH
              </button>
              {ready.some((d) => d.wifi) && (
                <button type="button" className="hud-link" onClick={onDisconnect} disabled={busy}>
                  DISCONNECT
                </button>
              )}
            </div>

            <div className="brain-field">
              <label htmlFor="android-host">CONNECT · IP ADDRESS &amp; PORT (WIRELESS DEBUGGING PAGE)</label>
              <div className="brain-inline">
                <input
                  id="android-host"
                  inputMode="decimal"
                  spellCheck={false}
                  autoComplete="off"
                  placeholder="192.168.1.7"
                  value={host}
                  onChange={(e) => takeHost(e.target.value, setPort)}
                  onKeyDown={(e) => e.key === "Enter" && canConnect && onConnect(host, port)}
                />
                <input
                  className="android-port"
                  inputMode="numeric"
                  autoComplete="off"
                  placeholder="port"
                  aria-label="Connect port"
                  value={port}
                  onChange={(e) => setPort(e.target.value.replace(/\D/g, ""))}
                  onKeyDown={(e) => e.key === "Enter" && canConnect && onConnect(host, port)}
                />
                <button type="button" className="hud-btn" disabled={!canConnect} onClick={() => onConnect(host, port)}>
                  CONNECT
                </button>
              </div>
            </div>

            {!pairing ? (
              <button type="button" className="hud-link android-pair-open" onClick={() => setPairing(true)}>
                FIRST TIME? PAIR WITH CODE
              </button>
            ) : (
              <div className="brain-field">
                <label htmlFor="android-pair-port">PAIR · &quot;PAIR DEVICE WITH PAIRING CODE&quot; ON THE PHONE</label>
                <div className="brain-inline">
                  <input
                    id="android-pair-port"
                    className="android-port"
                    inputMode="numeric"
                    autoComplete="off"
                    placeholder="pair port"
                    value={pairPort}
                    onChange={(e) => setPairPort(e.target.value.replace(/\D/g, ""))}
                  />
                  <input
                    className="android-port"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder="6-digit code"
                    aria-label="Pairing code"
                    maxLength={6}
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && canPair) {
                        onPair(host, pairPort, code);
                        setCode("");
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="hud-btn"
                    disabled={!canPair}
                    onClick={() => {
                      onPair(host, pairPort, code);
                      setCode("");
                    }}
                  >
                    PAIR
                  </button>
                </div>
              </div>
            )}

            <ol className="android-steps">
              <li>Phone: Settings › About phone › tap Build number 7 times.</li>
              <li>Developer options › Wireless debugging on (same WiFi as this PC).</li>
              <li>First time: Pair device with pairing code, then fill the IP, pair port and code above.</li>
              <li>Then FIND ON WIFI, or CONNECT with the port under IP address &amp; Port.</li>
              <li>USB instead: USB debugging on, plug in, tap Allow on the phone.</li>
            </ol>
          </>
        )}

        {busy && <div className="brain-note">Working…</div>}
        {!busy && state?.result && <div className={state.ok ? "brain-note" : "brain-error"}>{state.result}</div>}
      </div>
    </div>
  );
}
