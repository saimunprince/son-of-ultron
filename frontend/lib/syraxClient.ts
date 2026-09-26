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

export type TaskStatus =
  | "PENDING"
  | "IN_PROGRESS"
  | "BLOCKED"
  | "SUCCESS"
  | "PARTIAL"
  | "FAILED"
  | "CANCELLED"
  | "INTERRUPTED"
  | "UNKNOWN";

export type RecoveryState = "RESUMABLE" | "UNCERTAIN" | "BLOCKED" | "COMPLETED" | "FAILED" | "UNKNOWN";

export interface TaskSummary {
  task_id: string;
  goal: string;
  kind: string;
  status: TaskStatus;
  stage: string | null;
  current_step: number;
  created: number;
  updated: number;
  result: string | null;
  error: string | null;
  last_checkpoint_id: number | null;
}

export interface InterruptedTask {
  task_id: string;
  goal: string;
  step: number;
  stage: string | null;
  tool: string | null;
  question: string | null;
  recovery_state: RecoveryState;
  operation_state: string | null;
  when: number | null;
}

export interface RunningTask {
  task_id: string;
  goal: string;
  stage: string | null;
  step: number;
  status: TaskStatus | null;
}

export interface JournalEvent {
  id: number;
  ts: number;
  task_id: string | null;
  type: string;
  seq: number;
  payload: Record<string, unknown>;
}

export interface VerificationGate {
  name: string;
  required: boolean;
  status: "PASS" | "FAIL" | "NOT_VERIFIED";
  exit_code: number | null;
  duration_ms: number;
  evidence: string;
}

export interface Verification {
  id: number;
  ts: number;
  task_id: string | null;
  git_head: string | null;
  status: "GREEN" | "BLOCKED";
  gates: VerificationGate[];
}

export interface SelfCapability {
  capability: string;
  status: "VERIFIED" | "FAILING" | "NOT_TESTED" | "MISSING";
  uses: number;
  confidence: number | null;
}

export interface SelfWeakness {
  kind: string;
  detail: string;
  evidence: string;
}

/** The compact ("summary") self-model. Every value is measured or null. */
export interface SelfModelSummary {
  generated: number;
  identity: { name: string; version: string | null; stage: string; principles: string[]; boot_id: string; process_uptime_s: number };
  tasks_by_status: Record<string, number>;
  success_rate: number | null;
  running_task: RunningTask | null;
  interrupted: { task_id: string; goal: string; step: number | null; recovery_state: string | null; operation_state: string | null }[];
  last_verification: { status: "GREEN" | "BLOCKED"; git_head: string | null; ts: number; gates: { name: string; status: string }[] } | null;
  capabilities: SelfCapability[];
  weaknesses: SelfWeakness[];
  known_limitations: number;
  knowledge_count: number;
  runtime: {
    cpu: { cores: number | null; load_1_5_15: number[] | null };
    memory_mb: { total_mb: number | null; available_mb: number | null };
    brains: { active: string | null; ready: string[]; cooldown: string[]; needs_key: string[] } | null;
  };
}

export type ObjectiveStatus = "OPEN" | "ACTIVE" | "DONE" | "BLOCKED" | "DROPPED";

export interface Objective {
  id: number;
  key: string | null;
  goal: string;
  reason: string | null;
  priority: number;
  status: ObjectiveStatus;
  source: string;
  check_spec: Record<string, unknown>;
  evidence: Record<string, unknown>;
  progress: Record<string, unknown>;
  dependencies: number[];
  next_action: string | null;
  attempts: number;
  last_task_id: string | null;
  created: number;
  updated: number;
}

export interface CycleReport {
  started: number;
  outcome: "RAN" | "IDLE" | "SKIPPED" | "DISABLED" | "BUSY";
  reason: string | null;
  objective_id: number | null;
  task_id: string | null;
  task_status: TaskStatus | null;
  verdict: "DONE" | "RETRY" | "BLOCKED" | null;
  derived: number;
}

export interface AutonomyStatus {
  enabled: boolean;
  running_loop: boolean;
  interval_s: number;
  last_cycle: CycleReport | null;
  cycles: number;
  objectives: Record<ObjectiveStatus, number>;
}

export interface CheckpointSummary {
  id: number;
  task_id: string;
  seq: number;
  ts: number;
  stage: string;
  completed_steps: { step?: number; tool?: string; ok?: boolean }[];
  current_operation: Record<string, unknown> | null;
  verified: Record<string, unknown>;
  remaining: string | null;
  assumptions: unknown[];
  env: Record<string, unknown>;
  next_action: string | null;
  evidence_state: string;
  context_messages: number;
}

export interface TaskDetail {
  task: TaskSummary & { operation: Record<string, unknown> | null; recovery: Record<string, unknown> | null };
  events: JournalEvent[];
  checkpoints: CheckpointSummary[];
  objective: Objective | null;
}

export interface Knowledge {
  id: number;
  claim: string;
  kind: "web" | "local" | "experiment" | "human" | "conclusion";
  source_url: string | null;
  source_title: string | null;
  excerpt: string | null;
  confidence: number;
  basis: string;
  sources: (number | string)[];
  tags: string[];
  question: string | null;
  task_id: string | null;
  created: number;
  last_used: number | null;
  uses: number;
}

/** Fields the journal adds to every event it fanned out. */
export interface Journaled {
  task_id?: string;
  event_id?: number;
  ts?: number;
  unjournaled?: boolean;
}

export type ServerEvent =
  | {
      type: "hello";
      name: string;
      tools: string[];
      interrupted: InterruptedTask[];
      running: RunningTask | null;
      recent: TaskSummary[];
      autonomy: AutonomyStatus;
    }
  | ({ type: "brains" } & BrainsState)
  | { type: "brain"; event: "answered"; provider: string; label: string; model: string }
  | { type: "brain"; event: "failover"; provider: string; reason: string }
  | { type: "brain_models"; id: string; models: string[]; error?: string }
  | ({ type: "brain_test" } & BrainTestResult)
  | { type: "state"; state: "booting" | "idle" | "thinking" | "acting"; step?: number; tool?: string }
  | { type: "user"; text: string; voice?: boolean }
  | ({ type: "think"; step: number; content: string; tools: { id: string; name: string; args: unknown }[] } & Journaled)
  | ({ type: "tool_start"; id: string; name: string; args: unknown; step?: number } & Journaled)
  | ({ type: "tool_result"; id: string; name: string; ok: boolean; output: string; truncated: boolean; image?: string; step?: number } & Journaled)
  | ({ type: "ask"; question: string } & Journaled)
  | ({ type: "final"; text: string } & Journaled)
  | ({
      type: "task";
      event: "queued" | "started" | "completed" | "failed" | "cancelled" | "blocked" | "interrupted" | "unknown";
      goal?: string;
      status?: TaskStatus;
      result?: string;
      error?: string;
      step?: number;
      stage?: string | null;
      tool?: string | null;
      question?: string | null;
      recovery_state?: RecoveryState;
    } & Journaled)
  | ({ type: "checkpoint"; checkpoint_id: number; seq: number; stage: string; completed_steps: number; evidence_state: string } & Journaled)
  | ({ type: "recovery"; event: "started" | "verified" | "resumed" | "completed"; count?: number; task_ids?: string[] } & Journaled)
  | ({ type: "verification"; verification_id: number; status: "GREEN" | "BLOCKED"; git_head: string | null } & Journaled)
  | ({ type: "stage"; stage: string } & Journaled)
  | { type: "history"; tasks: TaskSummary[] }
  | { type: "task_events"; task_id: string; events: JournalEvent[] }
  | { type: "verifications"; verifications: Verification[] }
  | ({ type: "task_detail"; task_id: string } & TaskDetail)
  | { type: "replay"; since: number; until: number | null; events: JournalEvent[] }
  | { type: "knowledge_list"; query: string; knowledge: Knowledge[] }
  | ({ type: "research"; event: "started" | "completed"; question: string; sources?: number; fetched?: number; stored?: number; failures?: string[]; ms?: number } & Journaled)
  | ({ type: "knowledge"; event: "stored"; knowledge_id: number; kind: Knowledge["kind"]; confidence: number; claim: string; source_url: string | null; tags: string[] } & Journaled)
  | { type: "objectives"; objectives: Objective[] }
  | ({ type: "autonomy_status" } & AutonomyStatus)
  | ({ type: "autonomy"; event: "toggled"; enabled: boolean } & Journaled)
  | ({
      type: "objective";
      event: "created" | "updated" | "completed" | "blocked" | "dropped";
      objective_id: number;
      goal?: string;
      status?: ObjectiveStatus;
      priority?: number;
      source?: string;
      note?: string | null;
      attempts?: number;
    } & Journaled)
  | ({ type: "cycle"; event: "started" | "completed"; forced?: boolean; outcome?: CycleReport["outcome"]; reason?: string | null; verdict?: string | null } & Journaled)
  | ({ type: "reflection"; event: "created"; objective_id: number; verdict: string; lesson: string; attempt: number } & Journaled)
  | ({ type: "self_model"; section: "summary" } & SelfModelSummary)
  | { type: "self_model"; section: string; [key: string]: unknown }
  | { type: "notice"; text: string }
  | { type: "error"; message: string }
  | { type: "pong" };

export type ClientMessage =
  | { type: "task"; text: string; voice?: boolean }
  | { type: "answer"; text: string }
  | { type: "stop" }
  | { type: "reset" }
  | { type: "ping" }
  | { type: "history"; limit?: number }
  | { type: "task_events"; task_id: string }
  | { type: "verifications"; limit?: number }
  | { type: "resume"; task_id: string }
  | { type: "self_model"; section?: string }
  | { type: "objectives"; limit?: number }
  | { type: "objective_add"; goal: string; reason?: string; priority?: number }
  | { type: "autonomy"; enabled?: boolean }
  | { type: "cycle_now" }
  | { type: "task_detail"; task_id: string }
  | { type: "replay"; since?: number; until?: number }
  | { type: "knowledge"; query?: string; limit?: number }
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
