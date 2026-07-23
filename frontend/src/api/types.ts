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
  | "radio"
  | "checkbox"
  | "likert"
  | "free_text"
  | "choice_buttons"
  | "span_select";

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
  scale?: LikertScale;
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
