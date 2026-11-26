/* Microphone and speaker choice (2026-11-26). The device list comes from
 * navigator.mediaDevices.enumerateDevices(); labels stay empty until the page
 * has microphone permission, so unnamed devices get a numbered name. The choice
 * is remembered per browser in localStorage, which may be missing or throw.
 *
 * SYRAX's own voice plays through Web Audio, so a speaker choice needs
 * AudioContext.setSinkId (Chrome / Edge 110+). Where it is missing (Firefox,
 * Safari) the speaker choice is hidden and the system default is used. */

export type AudioKind = "audioinput" | "audiooutput";

export interface DeviceLike {
  deviceId: string;
  kind: string;
  label: string;
  groupId?: string;
}

export interface DeviceOption {
  /** "" is the system default */
  id: string;
  label: string;
}

export interface DeviceList {
  options: DeviceOption[];
  /** some devices have no name: the browser hides labels until the mic is allowed */
  needsPermission: boolean;
}

const NOUN: Record<AudioKind, string> = { audioinput: "Microphone", audiooutput: "Speaker" };
/** Chrome's pseudo-devices: "default" is our "" entry, "communications" is Windows' call device */
const PSEUDO = new Set(["default", "communications"]);

/** Options for one kind: the system default first, then each real device once, unnamed ones numbered. */
export function mapDevices(devices: readonly DeviceLike[], kind: AudioKind): DeviceList {
  const own = devices.filter((d) => d.kind === kind);
  const options: DeviceOption[] = [{ id: "", label: "System default" }];
  const seen = new Set<string>();
  let needsPermission = own.length > 0 && own.every((d) => !d.deviceId);
  let n = 0;
  for (const d of own) {
    if (!d.deviceId || PSEUDO.has(d.deviceId) || seen.has(d.deviceId)) continue;
    seen.add(d.deviceId);
    n += 1;
    const label = d.label.trim();
    if (!label) needsPermission = true;
    options.push({ id: d.deviceId, label: label || `${NOUN[kind]} ${n}` });
  }
  return { options, needsPermission };
}

/** The saved id when that device is still there, else the system default. */
export function pickDevice(options: readonly DeviceOption[], saved: string): string {
  return options.some((o) => o.id === saved) ? saved : "";
}

/** Microphone constraints SYRAX's listeners use, with the chosen device when there is one. */
export function micConstraints(deviceId?: string): MediaTrackConstraints {
  const base: MediaTrackConstraints = { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 };
  // "ideal", not "exact": an unplugged device falls back to the default instead of failing the mic
  return deviceId ? { ...base, deviceId: { ideal: deviceId } } : base;
}

export interface AudioPrefs {
  micId: string;
  speakerId: string;
  /** KeyboardEvent.code of the push-to-talk key */
  pttKey: string;
}

export const DEFAULT_PREFS: AudioPrefs = { micId: "", speakerId: "", pttKey: "Space" };
const PREFS_KEY = "syrax.audio";

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function storage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null; // a sandboxed frame throws on the bare access
  }
}

export function loadAudioPrefs(store: StorageLike | null = storage()): AudioPrefs {
  try {
    const raw = store?.getItem(PREFS_KEY);
    if (!raw) return { ...DEFAULT_PREFS };
    const v = JSON.parse(raw) as Partial<Record<keyof AudioPrefs, unknown>>;
    const str = (x: unknown, d: string) => (typeof x === "string" ? x : d);
    return {
      micId: str(v.micId, ""),
      speakerId: str(v.speakerId, ""),
      pttKey: typeof v.pttKey === "string" && v.pttKey ? v.pttKey : DEFAULT_PREFS.pttKey,
    };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

/** False when the browser would not keep it (no storage, quota, private mode): the choice still holds for this visit. */
export function saveAudioPrefs(prefs: AudioPrefs, store: StorageLike | null = storage()): boolean {
  try {
    if (!store) return false;
    store.setItem(PREFS_KEY, JSON.stringify(prefs));
    return true;
  } catch {
    return false;
  }
}

type SinkCtx = AudioContext & { setSinkId?: (id: string) => Promise<void> };

/** True when SYRAX's Web Audio voice can be sent to a chosen speaker. */
export function speakerChoiceSupported(): boolean {
  return typeof AudioContext !== "undefined" && "setSinkId" in AudioContext.prototype;
}

/** Route a Web Audio context to the speaker; best effort, the default stays on failure. */
export function applySink(ctx: AudioContext | null, speakerId: string): void {
  const c = ctx as SinkCtx | null;
  if (!c?.setSinkId || c.state === "closed") return;
  void c.setSinkId(speakerId).catch(() => {});
}
