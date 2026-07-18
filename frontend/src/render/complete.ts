// Submission gating (§2.3 required) and single-input auto-submit eligibility (§2.4).

import type { InputField, TemplateSchema } from "../api/types";
import { isOtherRaw } from "./options";

// Is a single input's raw answer present and non-empty?
export function inputAnswered(input: InputField, raw: unknown): boolean {
  if (raw === undefined || raw === null) return false;
  if (input.type === "checkbox") {
    return Array.isArray(raw) && raw.length > 0 && raw.every((v) => !emptyOther(v));
  }
  if (input.type === "free_text") {
    return typeof raw === "string" && raw.trim().length > 0;
  }
  if (typeof raw === "string") return raw.length > 0 && !emptyOther(raw);
  return true; // numbers (likert)
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
const AUTO_SUBMIT_TYPES = new Set(["radio", "likert", "choice_buttons"]);

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
