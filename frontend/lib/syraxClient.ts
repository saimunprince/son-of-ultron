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
  performance: {
    last_benchmark: { id: number; ts: number; status: BenchmarkRow["status"]; git_head: string | null; metrics: Record<string, number>; regressions: string[] } | null;
    benchmarks: number;
    last_quality: { id: number; ts: number; status: QualityRun["status"]; pass_rate: number; delta: number | null; brain: string | null; failed: string[] } | null;
    experiments: { count: number; recent: { id: number; verdict: ExperimentRow["verdict"]; metric: string; hypothesis: string }[] };
  };
  runtime: {
    cpu: { cores: number | null; load_1_5_15: number[] | null };
    memory_mb: { total_mb: number | null; available_mb: number | null };
    brains: { active: string | null; ready: string[]; cooldown: string[]; needs_key: string[] } | null;
    battery?: ResourceSnapshot["battery"];
    quiet_hours?: ResourceSnapshot["quiet_hours"];
    pressure?: string | null;
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

export interface ResourceSnapshot {
  ts: number;
  cpu: { cores: number; load_1_5_15: number[] | null; load_per_core: number | null };
  memory_mb: { total_mb: number | null; available_mb: number | null };
  disk: { free_gb: number; total_gb: number } | null;
  battery: { percent: number; status: string; discharging: boolean } | null;
  quiet_hours: { window: [number, number] | null; active: boolean };
}

export interface AutonomyStatus {
  enabled: boolean;
  running_loop: boolean;
  interval_s: number;
  last_cycle: CycleReport | null;
  cycles: number;
  objectives: Record<ObjectiveStatus, number>;
  resources: ResourceSnapshot;
  pressure: string | null;
  last_maintenance: string | null;
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

export interface SkillRow {
  name: string;
  version: number;
  purpose: string;
  path: string;
  status: "NOT_TESTED" | "VERIFIED" | "FAILED" | "DISABLED";
  tests_passed: number;
  tests_failed: number;
  evidence: Record<string, unknown>;
  dependencies: string[];
  known_limitations: string[];
  created_task_id: string | null;
  created: number;
  updated: number;
  last_verified: number | null;
  registered: boolean;
}

export type PresentationKind = "status" | "card" | "code" | "terminal" | "table" | "list" | "image" | "notification";

export interface PresentationElement {
  presentation_id: string;
  kind: PresentationKind;
  purpose: string;
  data: Record<string, unknown>;
  attention: "ambient" | "notice" | "focus";
  position: "stage" | "overlay";
  priority: number;
  ttl_s: number | null;
  replaces: string | null;
  dismiss_on: string[];
  slot: string | null;
  source: "engine" | "model";
  created: number;
  task_id: string | null;
}

export interface PresentationPlan {
  elements: PresentationElement[];
  minimal: boolean;
}

export interface BenchmarkRow {
  id: number;
  ts: number;
  git_head: string | null;
  metrics: Record<string, number>;
  status: "BASELINE" | "PASS" | "REGRESSION" | "NOT_VERIFIED";
  compared_to: number | null;
  deltas: Record<string, { now: number; before: number | null; pct: number | null; regression: boolean }>;
  task_id: string | null;
}

export interface ExperimentRow {
  id: number;
  ts: number;
  hypothesis: string;
  objective: string | null;
  baseline: Record<string, unknown>;
  candidate: Record<string, unknown>;
  metric: string;
  result: Record<string, unknown>;
  conclusion: string;
  verdict: "CANDIDATE_BETTER" | "BASELINE_BETTER" | "NO_DIFFERENCE" | "INCONCLUSIVE";
  next_action: string | null;
  task_id: string | null;
}

export interface QualityRun {
  id: number;
  ts: number;
  git_head: string | null;
  brain: string | null;
  results: { id: string; ok: boolean; task_id: string | null; status?: string; steps?: number; ms: number; checks: { check: string; ok: boolean; detail: string }[]; final?: string }[];
  pass_rate: number;
  status: "BASELINE" | "PASS" | "REGRESSION";
  compared_to: number | null;
  delta: number | null;
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
      presentation: PresentationPlan;
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
  | ({ type: "code"; event: "changed"; path?: string; command?: string; files?: Record<string, string>; stat?: string; head?: string } & Journaled)
  | ({ type: "commit"; event: "created" | "failed"; commit?: string; files?: string[]; summary?: string; verification_id?: number; error?: string } & Journaled)
  | ({ type: "rollback"; event: "created"; reason: string; restored: string[]; removed: string[]; clean: boolean; snapshot: string } & Journaled)
  | ({ type: "push"; event: "started" | "completed" | "failed"; ok?: boolean; branch?: string; output?: string } & Journaled)
  | ({ type: "presentation"; event: "created" } & PresentationElement & Journaled)
  | ({ type: "presentation"; event: "dismissed"; presentation_id: string; reason: string; kind: PresentationKind } & Journaled)
  | ({ type: "presentation_plan" } & PresentationPlan)
  | { type: "quality_runs"; runs: QualityRun[] }
  | ({ type: "quality"; event: "started" | "completed"; cases?: string[]; quality_id?: number; status?: QualityRun["status"]; pass_rate?: number; delta?: number | null; failed?: string[]; brain?: string | null } & Journaled)
  | { type: "benchmarks"; benchmarks: BenchmarkRow[] }
  | { type: "experiments"; experiments: ExperimentRow[] }
  | ({ type: "benchmark"; event: "completed"; benchmark_id: number; status: BenchmarkRow["status"]; compared_to: number | null; regressions: string[] } & Journaled)
  | ({ type: "experiment"; event: "started" | "completed"; hypothesis: string; verdict?: ExperimentRow["verdict"]; metric: string; experiment_id?: number } & Journaled)
  | ({ type: "maintenance"; event: "completed"; tasks_examined: number; events_pruned: number; checkpoint_contexts_trimmed: number; retain_days: number } & Journaled)
  | { type: "skills"; skills: SkillRow[] }
  | ({ type: "skill"; event: "created" | "verified" | "failed" | "disabled" | "not_tested"; skill: string; version?: number; status?: string; tests_passed?: number; tests_failed?: number; purpose?: string; note?: string | null } & Journaled)
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
  | { type: "skills" }
  | { type: "presentation" }
  | { type: "benchmarks"; limit?: number }
  | { type: "quality_run"; only?: string[] }
  | { type: "quality_runs"; limit?: number }
  | { type: "experiments"; limit?: number }
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
