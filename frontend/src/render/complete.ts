// Submission gating (§2.3 required) and single-input auto-submit eligibility (§2.4).

import type { InputField, TemplateSchema } from "../api/types";
import { isOtherRaw } from "./options";

// Answer shapes that are arrays: "answered" means at least one entry.
const ARRAY_TYPES = new Set(["checkbox", "multiselect", "tags", "ranking"]);
// Answer shapes typed into a text box: whitespace is not an answer.
const TEXT_TYPES = new Set(["free_text", "date", "datetime"]);

// Is a single input's raw answer present and non-empty?
export function inputAnswered(input: InputField, raw: unknown): boolean {
  if (raw === undefined || raw === null) return false;
  if (ARRAY_TYPES.has(input.type)) {
    return Array.isArray(raw) && raw.length > 0 && raw.every((v) => !emptyOther(v));
  }
  if (TEXT_TYPES.has(input.type)) {
    return typeof raw === "string" && raw.trim().length > 0;
  }
  if (input.type === "boolean") {
    // `false` *is* an answer — only "not yet touched" is missing, and that is the
    // undefined/null already handled above.
    return typeof raw === "boolean";
  }
  if (input.type === "number" || input.type === "slider") {
    if (typeof raw === "number") return Number.isFinite(raw);
    return typeof raw === "string" && raw.trim().length > 0 && Number.isFinite(Number(raw));
  }
  if (typeof raw === "string") return raw.length > 0 && !emptyOther(raw);
  return true; // numbers (likert, rating)
}

function emptyOther(v: unknown): boolean {
  return isOtherRaw(v) && (v as string).slice("other:".length).trim().length === 0;
}

// All required inputs answered → submission allowed.
export function isComplete(schema: TemplateSchema, answers: Record<string, unknown>): boolean {
  return schema.inputs
    .filter((i) => i.required)
    .every((i) => inputAnswered(i, answers[i.id]));
}

// §2.4: a template with a single required input auto-submits on one keystroke.
// Restricted to choice-type inputs (typing/multi-select shouldn't fire early).
const AUTO_SUBMIT_TYPES = new Set([
  "radio",
  "likert",
  "choice_buttons",
  "rating",
  "boolean",
]);

export function autoSubmitInputId(schema: TemplateSchema): string | null {
  const required = schema.inputs.filter((i) => i.required);
  if (required.length !== 1) return null;
  const only = required[0];
  // Other inputs (non-required) must not exist for a clean one-keystroke flow…
  // but non-required extras are fine; the single *required* input drives submit.
  if (!AUTO_SUBMIT_TYPES.has(only.type)) return null;
  if (schema.inputs.length !== 1) return null; // extra inputs → let the user choose to submit
  return only.id;
}
