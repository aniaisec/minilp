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
  value?: Record<string, unknown> | null;
  confidence?: number | null;
  reasoning?: string | null;
  comment?: string | null;
}

export interface LabelOut {
  id: number;
  slot_id: number;
  unit_id: number;
  annotator_id: number;
  value: Record<string, unknown>;
  is_valid: boolean;
}
