/* Chrome / Edge speech recognition (Google / Azure, free, no key).
 * Continuous, with live interim text and automatic restarts. When the browser
 * lacks it or the service is unreachable, callers fall back to Whisper. */

interface RecAlt {
  transcript: string;
}
interface RecResult {
  isFinal: boolean;
  0: RecAlt;
  length: number;
}
interface RecEvent {
  resultIndex: number;
  results: ArrayLike<RecResult>;
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((e: RecEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onspeechstart: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecCtor = new () => Recognition;

function ctor(): RecCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecCtor; webkitSpeechRecognition?: RecCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const webSpeechAvailable = () => ctor() !== null;

export interface WebSpeechHandlers {
  onFinal: (text: string) => void;
  onInterim?: (text: string) => void;
  onSpeechStart?: () => void;
  /** fatal: the engine cannot work here (caller should fall back) */
  onUnavailable?: (reason: string) => void;
  onDenied?: () => void;
}

export class WebSpeechEar {
  private rec: Recognition | null = null;
  private running = false;
  private restarts = 0;
  private startedAt = 0;
  private heardSomething = false;

  constructor(private h: WebSpeechHandlers) {}

  start(lang: string) {
    const Ctor = ctor();
    if (!Ctor) {
      this.h.onUnavailable?.("not supported in this browser");
      return;
    }
    this.stop();
    const rec = new Ctor();
    rec.lang = lang;
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.onspeechstart = () => this.h.onSpeechStart?.();
    rec.onresult = (e) => {
      this.heardSomething = true;
      this.restarts = 0;
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        const text = r[0]?.transcript ?? "";
        if (r.isFinal) {
          if (text.trim()) this.h.onFinal(text.trim());
        } else {
          interim += text;
        }
      }
      this.h.onInterim?.(interim.trim());
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed") {
        this.running = false;
        this.h.onDenied?.();
      } else if (e.error === "service-not-allowed" || e.error === "language-not-supported") {
        this.running = false;
        this.h.onUnavailable?.(e.error);
      } else if (e.error === "network" && !this.heardSomething) {
        // Chromium builds without Google keys fail like this on every start.
        this.running = false;
        this.h.onUnavailable?.("speech service unreachable");
      }
      // "no-speech", "aborted", transient "network": onend restarts us
    };
    rec.onend = () => {
      this.h.onInterim?.("");
      if (!this.running) return;
      // Chrome ends sessions on its own every so often; keep listening.
      const quickDeath = performance.now() - this.startedAt < 1000;
      this.restarts = quickDeath ? this.restarts + 1 : 0;
      if (this.restarts > 5) {
        this.running = false;
        this.h.onUnavailable?.("recognition keeps stopping");
        return;
      }
      setTimeout(() => this.boot(), quickDeath ? 400 : 50);
    };
    this.rec = rec;
    this.running = true;
    this.heardSomething = false;
    this.boot();
  }

  private boot() {
    if (!this.running || !this.rec) return;
    this.startedAt = performance.now();
    try {
      this.rec.start();
    } catch {
      /* already started */
    }
  }

  stop() {
    this.running = false;
    try {
      this.rec?.abort();
    } catch {
      /* ignore */
    }
    this.rec = null;
  }
}
