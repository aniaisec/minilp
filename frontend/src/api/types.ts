// Types mirroring the backend template schema (§2.1–§2.4) and API payloads (§5).
// Kept structural and permissive: the backend is the source of truth for
// validation; the renderer only needs enough shape to draw and collect answers.

export type Arrangement = "stack" | "split" | "columns";
export type WidthToken = "md" | "lg" | "xl" | "full";
export type Density = "comfortable" | "compact";

export interface Layout {
  arrangement?: Arrangement;
  ratio?: number[];
  width?: WidthToken;
  density?: Density;
}

export type DisplayType =
  | "text"
  | "markdown"
  | "image"
  | "audio"
  | "code"
  | "html_snippet"
  | "panel_group";

export interface DisplayBlock {
  type: DisplayType;
  source?: string;
  sources?: string[];
  optional?: boolean;
  render?: Record<string, unknown>;
}

export type InputType =
  // v1 (M1–M5)
  | "radio"
  | "checkbox"
  | "likert"
  | "free_text"
  | "choice_buttons"
  | "span_select"
  // M6 builder palette (§2.1)
  | "number"
  | "select"
  | "multiselect"
  | "boolean"
  | "rating"
  | "slider"
  | "tags"
  | "ranking"
  | "date"
  | "datetime";

export interface LikertScale {
  min?: number;
  max?: number;
  labels?: string[];
}

export interface InputField {
  id: string;
  type: InputType;
  label?: string;
  options?: string[];
  allow_other?: boolean;
  required?: boolean;
  hotkeys?: "auto" | string[];
  /** likert / rating — a labeled ordinal scale. */
  scale?: LikertScale;
  /** number / slider — continuous bounds. */
  min?: number;
  max?: number;
  step?: number;
  /** Help text rendered under the field label. */
  help?: string;
}

export interface VariantSpec {
  dimension: string;
  values: string[];
  balance?: "strict" | "soft";
}

export interface TemplateSchema {
  name: string;
  version?: number;
  description?: string | null;
  layout?: Layout;
  display?: DisplayBlock[];
  inputs: InputField[];
  variants?: VariantSpec | null;
}

export interface Template {
  id: number;
  name: string;
  version: number;
  description?: string | null;
  kind: string;
  schema: TemplateSchema;
}

export interface Project {
  id: number;
  name: string;
  template_id: number;
  template_version: number;
  labels_per_unit: number;
  max_labels_per_unit: number;
  gold_ratio: number;
  guidelines_md?: string | null;
}

// GET /tasks/next — deliberately blind (never exposes is_gold); §5.
export interface Task {
  slot_id: number;
  unit_id: number;
  project_id: number;
  payload: Record<string, unknown>;
  variant?: Record<string, unknown> | null;
  lease_expires_at?: string | null;
}

// POST /tasks/{slot}/submit
export interface SubmitRequest {
  raw: Record<string, unknown>;
  // Canonical value. Advisory since M4 — the backend recomputes it from `raw`
  // plus the slot's variant (§2.6). Still sent so an offline/legacy client and
  // the server can be compared.
  value?: Record<string, unknown> | null;
  confidence?: number | null;
  reasoning?: string | null;
  comment?: string | null;
  latency_ms?: number | null;
}

// The blinded quality summary the submit response carries (§6.1). It never says
// whether the unit was a gold or how peers voted — only what concerns this
// annotator's own standing.
export interface LabelQuality {
  paused: boolean;
  labels_voided: number;
  reputation: number | null;
  flags: string[];
}

export interface LabelOut {
  id: number;
  slot_id: number;
  unit_id: number;
  annotator_id: number;
  value: Record<string, unknown>;
  is_valid: boolean;
  quality?: LabelQuality | null;
}

// ---- M5 admin / analytics (§9, §11) ----------------------------------------

export interface ProjectSummary {
  id: number;
  name: string;
  description?: string | null;
  template_id: number;
  template_version: number;
  labels_per_unit: number;
  gold_ratio: number;
}

export interface Batch {
  id: number;
  project_id: number;
  name?: string | null;
  source_filename?: string | null;
  unit_count: number;
  rejected_count: number;
}

export interface UnitSummary {
  id: number;
  project_id: number;
  batch_id: number | null;
  payload: Record<string, unknown>;
  priority: number;
  is_gold: boolean;
  status: string;
}

// GET /projects/{id}/progress
export interface Progress {
  project_id: number;
  labels_per_unit: number;
  max_labels_per_unit: number;
  funnel: {
    pending: number;
    in_progress: number;
    labeled: number;
    finalized: number;
    total: number;
    escalated: number;
  };
  slots: { open: number; leased: number; filled: number; voided: number };
  labels_total: number;
  batches: {
    batch_id: number | null;
    name: string | null;
    unit_count: number;
    rejected_count: number;
    status_counts: Record<string, number>;
    done: number;
    total: number;
    fill_rate: number;
  }[];
  variants: {
    dimension: string | null;
    balanced: boolean;
    values: {
      value: string | null;
      filled: number;
      open: number;
      leased: number;
      total: number;
      fill_rate: number;
    }[];
  };
  consensus: {
    complete_units: number;
    keys: Record<string, { agreed: number; complete: number; rate: number | null }>;
  };
  throughput: {
    labels_per_hour: number;
    window_hours: number;
    labels_in_window: number;
    remaining_slots: number;
    eta_hours: number | null;
  };
}

export interface Estimate {
  estimate: number;
  ci_low: number;
  ci_high: number;
  n: number;
}

export interface BiasGroup {
  n_positional_labels: number;
  prefer_first_rate: Estimate;
  bias_score: number | null;
  annotators: {
    annotator_id: number;
    first: number;
    second: number;
    preference: Estimate;
    bias_score: number | null;
  }[];
}

// GET /projects/{id}/analytics/bias
export interface Bias {
  project_id: number;
  humans: BiasGroup;
  judges: BiasGroup;
  order_sensitivity: {
    measurable_units: number;
    flipped_units: number;
    flip_rate: number | null;
    units: { unit_id: number; flipped: boolean; keys: Record<string, unknown> }[];
  };
  adjusted_outcomes: {
    keys: Record<string, { overall: Record<string, number>; by_variant: Record<string, Record<string, number>> }>;
  };
}

// GET /projects/{id}/analytics/distribution
export interface Distribution {
  project_id: number;
  keys: Record<
    string,
    { total: number; overall: Record<string, number>; by_kind: Record<string, Record<string, number>> }
  >;
}

// GET /projects/{id}/annotators
export interface Roster {
  project_id: number;
  count: number;
  annotators: {
    annotator_id: number;
    kind: string;
    display_name: string | null;
    status: string;
    pause_reason: string | null;
    reputation: number;
    labels_valid: number;
    labels_voided: number;
    gold_passes: number;
    gold_total: number;
    gold_accuracy: number | null;
  }[];
}

// GET /units/{id}
export interface UnitDetail {
  unit_id: number;
  project_id: number;
  batch_id: number | null;
  status: string;
  priority: number;
  is_gold: boolean;
  gold_expected: Record<string, unknown> | null;
  escalated_at: string | null;
  payload: Record<string, unknown>;
  slots: Record<string, number>;
  labels: {
    label_id: number;
    slot_id: number;
    annotator_id: number;
    annotator_kind: string | null;
    annotator_name: string | null;
    reputation: number | null;
    variant: Record<string, unknown> | null;
    raw: Record<string, unknown>;
    value: Record<string, unknown>;
    confidence: number | null;
    is_valid: boolean;
    submitted_at: string | null;
  }[];
  consensus: Record<string, unknown> | null;
  quality_snapshot: Record<string, unknown> | null;
}

// GET /tasks/available?annotator= — the annotator landing page (§11).
export interface AvailableProject {
  project_id: number;
  name: string;
  description?: string | null;
  template_id: number;
  template_version: number;
  labels_per_unit: number;
  available_labels: number;
  open_units: number;
  your_labels: number;
  eligible: boolean;
  blocked_reason: string | null;
}

export interface AvailableWork {
  annotator_id: number;
  projects: AvailableProject[];
}

export interface IngestReport {
  batch_id: number | null;
  unit_count: number;
  rejected_count: number;
  rejected_rows: { row: number; errors: string[] }[];
  accepted_rows: { row: number; unit_id: number }[];
}

// GET /templates/{id}/sample — example payload + field breakdown (§11 gallery).
export interface TemplateSample {
  template_id: number;
  saved: boolean;
  sample: Record<string, unknown>;
  fields: { required: string[]; optional: string[] };
}

export type PayloadFormat = "json" | "tsv";

// ---- M6 authoring + export (§2.5, §10) --------------------------------------

/** PATCH /projects/{id} — every field optional; only what is sent changes. */
export interface ProjectPatch {
  name?: string;
  description?: string | null;
  guidelines_md?: string | null;
  labels_per_unit?: number;
  max_labels_per_unit?: number;
  agreement?: Record<string, unknown> | null;
  gold_ratio?: number;
  lease_minutes?: number;
  min_reputation?: number;
  /** A schema differing from the bound template clones-and-rebinds it. */
  template_schema?: TemplateSchema;
}

export interface ProjectPatchResult {
  project: Project;
  /** True when the edit cloned the template and rebound the project to the copy. */
  rebound: boolean;
  /** Slots added (K raised) or removed (K lowered) across the project's units. */
  slots_changed: number;
  template_id?: number;
  template_version?: number;
}

export type ExportFormat = "labels" | "raw" | "preference" | "sft";

// GET /annotators/{id}/report (§5, §6.2)
export interface AnnotatorReport {
  annotator_id: number;
  kind: string;
  display_name?: string | null;
  status: string;
  pause_reason?: string | null;
  reputation_score: number;
  live: {
    score: number;
    gold_accuracy: number | null;
    gold_samples: number;
    peer_agreement: number | null;
    agreement_samples: number;
    variant_bias: number | null;
    bias_samples: number;
    speed_flags: number;
  };
  events: { id: number; kind: string; delta: number; created_at: string | null }[];
}

// ---- M7 judges + webhooks (§5, §7.1, §7.3) ----------------------------------

export type ProviderName = "mock" | "anthropic" | "openai" | "openai_compatible";

/** POST /judges — a judge config. Note there is no api_key field: `params.
 *  api_key_env` names an environment variable the *server* reads at call time. */
export interface JudgeConfigCreate {
  name: string;
  provider: string;
  model_id: string;
  params?: Record<string, unknown> | null;
  prompt_template?: string | null;
  budget?: JudgeBudget | null;
}

export interface JudgeBudget {
  project_usd?: number | null;
  daily_usd?: number | null;
  max_tokens?: number | null;
  max_labels?: number | null;
}

export interface JudgeConfig {
  id: number;
  name: string;
  provider: string;
  model_id: string;
  params?: Record<string, unknown> | null;
  prompt_template?: string | null;
  prompt_version: number;
  budget?: JudgeBudget | null;
}

export interface JudgeSpend {
  cost_usd: number;
  daily_usd: number;
  tokens: number;
  labels: number;
  cache_hits: number;
}

/** GET /projects/{id}/judges — enrolled judges with live spend against caps. */
export interface EnrolledJudge {
  judge_config_id: number;
  annotator_id: number | null;
  display_name: string;
  provider: string;
  model_id: string;
  prompt_version: number;
  budget?: JudgeBudget | null;
  /** False when no price is known for the model — "$0.00" would be a lie. */
  priced: boolean;
  price_source: string;
  spend: JudgeSpend | null;
}

export interface JudgeRunError {
  stage: string;
  unit_id?: number;
  error: string;
  level?: string;
}

export interface JudgeRunReport {
  run_id: number | null;
  project_id: number;
  judge_config_id: number;
  annotator_id: number | null;
  dry_run: boolean;
  status: string;
  stopped_reason: string | null;
  slots_attempted: number;
  labels_written: number;
  cache_hits: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  estimated_cost_usd: number | null;
  errors: JudgeRunError[];
  budget?: JudgeBudget | null;
  webhooks_fired: number;
}

export interface JudgeRunResponse {
  project_id: number;
  dry_run: boolean;
  runs: JudgeRunReport[];
  labels_written: number;
  cost_usd: number;
  estimated_cost_usd: number | null;
}

/** GET /projects/{id}/judge-runs — the run history rows. */
export interface JudgeRunRow {
  id: number;
  project_id: number;
  judge_config_id: number;
  annotator_id: number | null;
  dry_run: boolean;
  status: string;
  stopped_reason: string | null;
  slots_attempted: number;
  labels_written: number;
  cache_hits: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  estimated_cost_usd: number | null;
  errors: JudgeRunError[] | null;
  started_at: string;
  finished_at: string | null;
}

// GET /projects/{id}/analytics/costs (§5)
export interface Costs {
  project_id: number;
  judges: {
    annotator_id: number;
    display_name: string | null;
    judge_config_id: number | null;
    provider: string | null;
    model_id: string | null;
    prompt_version: number | null;
    labels: number;
    cost_usd: number;
    tokens_in: number;
    tokens_out: number;
    cache_hits: number;
    cache_hit_rate: number | null;
    cost_per_label: number | null;
    avg_latency_ms: number | null;
    budget: JudgeBudget | null;
  }[];
  totals: {
    labels: number;
    judge_labels: number;
    human_labels: number;
    cost_usd: number;
    tokens: number;
    cache_hits: number;
    cache_hit_rate: number | null;
    cost_per_judge_label: number | null;
  };
}

export type WebhookEvent =
  | "budget.cap_reached"
  | "gold.accuracy_dropped"
  | "review.queue_backlog"
  | "project.completed";

export interface Webhook {
  id: number;
  event: string;
  target_url: string;
  project_id: number | null;
  status: string;
  /** The secret itself is never returned by the API — only whether one is set. */
  has_secret: boolean;
}

export interface WebhookDelivery {
  id: number;
  webhook_id: number;
  event: string;
  project_id: number | null;
  payload: Record<string, unknown>;
  status: string;
  attempts: number;
  status_code: number | null;
  error: string | null;
  created_at: string;
}

// ---- template deletion + identity (§2.5, §5) --------------------------------

export interface TemplateDeleteResult {
  name: string;
  count: number;
  deleted: { id: number; name: string; version: number }[];
}

/** A project standing in the way of a delete — named, so the refusal is actionable. */
export interface TemplateBlocker {
  project_id: number;
  name: string;
  template_id: number;
  template_version: number;
}

export interface TemplateUsage {
  template_id: number;
  kind: string;
  /** False for builtins and for any version a project is bound to. */
  deletable: boolean;
  projects: TemplateBlocker[];
  /** Projects on any version sharing this name — what a lineage delete must clear. */
  lineage_projects: TemplateBlocker[];
  versions: number;
}

// GET /me — the authenticated user and their rater record, if they have one.
export interface Me {
  user_id: number;
  email: string | null;
  role: string;
  annotator_id: number | null;
  display_name: string | null;
  status: string | null;
  reputation_score: number | null;
}

// POST /me:annotator — get-or-create; the same shape as AnnotatorOut.
export interface AnnotatorSelf {
  id: number;
  kind: string;
  display_name: string | null;
  status: string;
  reputation_score: number;
  pause_reason?: string | null;
}

// --- M8: merge, routing + review queue (§7.2) -------------------------------

/** One rater's contribution to a merged proposal, as the review queue shows it. */
export interface MergeVote {
  label_id: number;
  annotator_id: number;
  kind: string;
  name: string | null;
  /** Judge config name for model raters; null for humans. */
  judge: string | null;
  reputation: number;
  /** The rater's weight in the calibration-weighted merge (= live reputation). */
  weight: number;
  variant: Record<string, unknown> | null;
  value: Record<string, unknown>;
  raw: Record<string, unknown>;
  confidence: number | null;
  reasoning: string | null;
  cost_usd: number | null;
}

export interface MergeCandidate {
  value: unknown;
  weight: number;
  support: number;
  share: number;
}

export interface MergeKey {
  winner: unknown;
  weight: number;
  total_weight: number;
  share: number;
  support: number;
  votes: number;
  entropy: number;
  candidates: MergeCandidate[];
}

export interface MergeProposal {
  unit_id: number;
  method: string;
  value: Record<string, unknown>;
  confidence: number;
  entropy: number;
  votes: MergeVote[];
  keys: Record<string, MergeKey>;
}

export interface ReviewItem {
  unit_id: number;
  project_id: number;
  project_name: string;
  batch_id: number | null;
  priority: number;
  is_gold: boolean;
  status: string;
  escalated_at: string | null;
  escalation_reason: string | null;
  failed_keys: string[];
  payload: Record<string, unknown>;
  proposal: MergeProposal | null;
  consensus_snapshot: Record<string, unknown>;
  /** Present only on GET /review/{unit_id} — enough to render the answer widgets. */
  template?: { id: number; name: string; version: number; schema: TemplateSchema } | null;
  guidelines_md?: string | null;
  final_label?: {
    value: Record<string, unknown>;
    method: string;
    confidence: number | null;
    decided_by: number | null;
  } | null;
}

export interface ReviewQueue {
  project_id: number | null;
  depth: number;
  threshold: number | null;
  items: ReviewItem[];
}

export interface ReviewOutcome {
  unit_id: number;
  decision: "approve" | "override";
  method: string;
  final_label_id: number;
  value: Record<string, unknown>;
  confidence: number | null;
  queue_depth: number;
  webhooks_fired: number;
}

export interface Pipeline {
  project_id: number;
  pipeline: Record<string, unknown>[];
  is_default: boolean;
  stages: string[];
  variables: string[];
}
