export type BrainTier = "no-key" | "local" | "free" | "paid";

export interface BrainProvider {
  id: string;
  label: string;
  tier: BrainTier;
  note: string;
  signup_url: string;
  key_required: boolean;
  has_key: boolean;
  key_hint: string;
  model: string;
  enabled: boolean;
  status: "ready" | "cooldown" | "no-key" | "off";
  reason: string;
  cooldown_s: number;
}

export interface BrainsState {
  order: string[];
  providers: BrainProvider[];
  active: string | null;
}

export interface BrainTestResult {
  id: string;
  ok: boolean;
  tools?: boolean;
  model?: string;
  latency_ms?: number;
  reply?: string;
  error?: string;
}

export type BrainChange = { api_key?: string; model?: string; enabled?: boolean };

export type ServerEvent =
  | { type: "hello"; name: string; tools: string[] }
  | ({ type: "brains" } & BrainsState)
  | { type: "brain"; event: "answered"; provider: string; label: string; model: string }
  | { type: "brain"; event: "failover"; provider: string; reason: string }
  | { type: "brain_models"; id: string; models: string[]; error?: string }
  | ({ type: "brain_test" } & BrainTestResult)
  | { type: "state"; state: "booting" | "idle" | "thinking" | "acting"; step?: number; tool?: string }
  | { type: "user"; text: string; voice?: boolean }
  | { type: "think"; step: number; content: string; tools: { id: string; name: string; args: unknown }[] }
  | { type: "tool_start"; id: string; name: string; args: unknown }
  | { type: "tool_result"; id: string; name: string; ok: boolean; output: string; truncated: boolean; image?: string }
  | { type: "ask"; question: string }
  | { type: "final"; text: string }
  | { type: "notice"; text: string }
  | { type: "error"; message: string }
  | { type: "pong" };

export type ClientMessage =
  | { type: "task"; text: string; voice?: boolean }
  | { type: "answer"; text: string }
  | { type: "stop" }
  | { type: "reset" }
  | { type: "ping" }
  | { type: "brains_get" }
  | { type: "brains_save"; providers: Record<string, BrainChange>; order?: string[] }
  | { type: "brain_models"; id: string; api_key?: string }
  | { type: "brain_test"; id: string };

export type LinkState = "connecting" | "online" | "offline";

export const DEFAULT_WS_URL =
  process.env.NEXT_PUBLIC_SYRAX_WS ?? "ws://127.0.0.1:8765/ws";

/** HTTP base of the same backend (for /stt and /tts). */
export const API_BASE = DEFAULT_WS_URL.replace(/^ws(s?):/, "http$1:").replace(/\/ws\/?$/, "");

interface Handlers {
  onEvent: (e: ServerEvent) => void;
  onLink: (s: LinkState) => void;
}

/** WebSocket link to the SYRAX backend with exponential-backoff reconnect. */
export class SyraxClient {
  private ws: WebSocket | null = null;
  private retry = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private stopped = false;

  constructor(
    private url: string,
    private handlers: Handlers,
  ) {}

  connect() {
    this.stopped = false;
    this.open();
  }

  private open() {
    if (this.stopped) return;
    this.handlers.onLink("connecting");
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.retry = 0;
      this.handlers.onLink("online");
      this.heartbeat = setInterval(() => this.send({ type: "ping" }), 25000);
    };
    ws.onmessage = (msg) => {
      try {
        this.handlers.onEvent(JSON.parse(msg.data as string) as ServerEvent);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      this.clearHeartbeat();
      this.ws = null;
      this.handlers.onLink("offline");
      this.scheduleReconnect();
    };
    ws.onerror = () => ws.close();
  }

  private scheduleReconnect() {
    if (this.stopped || this.timer) return;
    const delay = Math.min(15000, 800 * 2 ** this.retry++);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.open();
    }, delay);
  }

  private clearHeartbeat() {
    if (this.heartbeat) clearInterval(this.heartbeat);
    this.heartbeat = null;
  }

  send(msg: ClientMessage): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  close() {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.clearHeartbeat();
    this.ws?.close();
    this.ws = null;
  }
}
