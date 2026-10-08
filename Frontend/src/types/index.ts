// Mirrors the backend Pydantic models (Backend/app/...).

export type Stage = "unverified" | "verified" | "awaiting_confirmation" | "escalated";

export interface OfferedSlot {
  slot_id: string;
  provider_name: string;
  specialty: string;
  label: string;
}

export interface PendingAction {
  id: string;
  kind: "book" | "reschedule" | "cancel";
  summary: string;
  created_turn: number;
}

export interface SessionState {
  stage: Stage;
  turn: number;
  patient_id: string | null;
  patient_first_name: string | null;
  verify_attempts: number;
  offered_slots: Record<string, OfferedSlot>;
  pending: PendingAction | null;
  completed: string[];
  escalation_reason: string | null;
}

export interface ToolEvent {
  seq: number;
  turn: number;
  tool: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
  denied_by: string | null;
  stage_after: Stage;
}

export interface TurnResult {
  session_id: string;
  reply: string;
  stage: Stage;
  state: SessionState;
  tool_events: ToolEvent[];
  flags: string[];
}

export interface NewSessionResponse {
  session_id: string;
  greeting: string;
  policy_version: string;
  database: string;
  model: string;
}

export interface ClinicInfo {
  clinic: Record<string, string>;
  providers: { id: string; name: string; specialty: string; weekdays: number[] }[];
  patients: { name: string; dob: string; appointments: string[] }[];
  now: string;
  database: string;
}

export interface Health {
  ok: boolean;
  database: string;
  active_policy: string;
  awaiting_review: string[];
  models: Record<string, string>;
}

export interface SummaryBlock {
  passed: number;
  total: number;
  mean_score: number;
}

export interface RunSummary {
  overall: SummaryBlock;
  train: SummaryBlock;
  holdout: SummaryBlock;
  by_category: Record<string, SummaryBlock>;
  errors: number;
  error_trials: number;
}

export interface RunListItem {
  run_id: string;
  policy_version: string;
  created_at: string;
  trials_per_scenario: number;
  summary: RunSummary;
}

export interface CheckResult {
  type: string;
  critical: boolean;
  passed: boolean;
  detail: string;
}

export interface JudgeScore {
  id: string;
  score: number;
  reason: string;
  critical: boolean;
  passed: boolean;
}

export interface TranscriptLine {
  role: "patient" | "agent";
  text: string;
  turn: number;
}

export interface TrialResult {
  scenario_id: string;
  trial: number;
  status: "ok" | "error";
  passed: boolean;
  score: number;
  critical_failures: string[];
  checks: CheckResult[];
  judge: { scores?: JudgeScore[]; normalized?: number; summary?: string };
  transcript: TranscriptLine[];
  tool_trace: ToolEvent[];
  flags: string[];
  ended_by: string;
  error: string | null;
}

export interface ScenarioResult {
  scenario_id: string;
  split: "train" | "holdout";
  category: string;
  description: string;
  trials: TrialResult[];
  pass_rate: number;
  passed: boolean;
  mean_score: number;
  status: "ok" | "error";
}

export interface RunResult extends RunListItem {
  models: Record<string, string>;
  results: ScenarioResult[];
}

export interface Scenario {
  id: string;
  split: "train" | "holdout";
  category: string;
  description: string;
}

export interface PolicyVersion {
  version: string;
  parent: string | null;
  status: "active" | "candidate" | "awaiting_review" | "rejected" | "superseded";
  file: string;
  created_at: string;
  notes: string;
  patch: unknown;
}

export interface CompareRow {
  scenario_id: string;
  split: string;
  category: string;
  before_pass_rate: number;
  after_pass_rate: number;
  before_passed: boolean;
  after_passed: boolean;
  before_score: number;
  after_score: number;
  change: string;
}

export interface Proposal {
  failure_cluster: string;
  root_cause: string;
  fix_type: string;
  target_scenarios: string[];
  expected_effect: string;
  code_change_ticket?: string | null;
}

export interface Gate {
  accepted: boolean;
  rules: Record<string, boolean>;
  reasons: string[];
  table: CompareRow[];
}

export interface Attempt {
  attempt: number;
  proposals: Proposal[];
  code_tickets: Proposal[];
  applied_edits: string[];
  rejected_edits: string[];
  candidate_version: string | null;
  candidate_run_id: string | null;
  diff: string;
  gate: Gate | null;
  rechecked: string[];
  accepted: boolean;
  note: string;
}

export interface LoopReport {
  loop_id: string;
  created_at: string;
  trials: number;
  start_version: string;
  final_version: string;
  first_run_id: string;
  final_run_id: string;
  iterations: {
    iteration: number;
    baseline_version: string;
    baseline_run_id: string;
    failing_train: string[];
    attempts: Attempt[];
    accepted_version: string | null;
  }[];
  before_after: CompareRow[];
  summary_before: RunSummary;
  summary_after: RunSummary;
  outcome: string;
  review_mode: boolean;
  awaiting_review: string | null;
}

export interface LoopListItem {
  loop_id: string;
  created_at: string;
  start_version: string;
  final_version: string;
  outcome: string;
  summary_before: RunSummary;
  summary_after: RunSummary;
}

export interface JobInfo {
  id: string;
  kind: "eval" | "loop";
  status: "running" | "done" | "error";
  created_at: string;
  result: Record<string, unknown> | null;
  error: string | null;
}

// Events streamed from /api/jobs/{id}/events
export type JobEvent = { type: string; [key: string]: any };
