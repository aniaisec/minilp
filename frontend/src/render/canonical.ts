// Canonicalization: raw answer (what was entered) → value (canonical) — §2.3, §2.8.
//
// Two rules are exercised by the gallery:
//   1. allow_other:  raw "other:capybara" → value "capybara" (radio),
//      and element-wise for checkbox arrays.
//   2. panel_order variant: a positional choice (Left/Tie/Right) canonicalizes
//      to the item chosen (A/Tie/B), using the slot's variant so bias is
//      measurable and Left/Right identity never leaks to the annotator (§2.7, §4).
//
// value === raw for variant-free templates with no Other selection.

import type { InputField, TemplateSchema } from "../api/types";

export const OTHER_PREFIX = "other:";

function stripOther(v: unknown): unknown {
  if (typeof v === "string" && v.startsWith(OTHER_PREFIX)) {
    return v.slice(OTHER_PREFIX.length);
  }
  return v;
}

// Map a positional label to the canonical item under a variant string.
// "Left"/"Right" → variant[0]/variant[1]; "Tie" and anything else pass through.
function canonicalizePositional(label: unknown, variant: string | null): unknown {
  if (typeof label !== "string" || !variant) return label;
  const l = label.trim().toLowerCase();
  if (l === "left") return variant[0] ?? label;
  if (l === "right") return variant[variant.length - 1] ?? label;
  return label; // tie, center, etc.
}

// --- M6 value-shape canonicalizers (§2.3) ----------------------------------
// Mirrors backend `services/quality/canonical.py`. The server recomputes all of
// this and its answer is the one that's stored (§2.6) — keeping the two in step
// is what lets a client-side preview show the value that will actually be saved.

const TRUE_TOKENS = new Set(["true", "yes", "y", "1", "on"]);
const FALSE_TOKENS = new Set(["false", "no", "n", "0", "off"]);

function toBool(raw: unknown): unknown {
  if (typeof raw === "boolean") return raw;
  if (typeof raw === "number") return raw !== 0;
  if (typeof raw === "string") {
    const token = raw.trim().toLowerCase();
    if (TRUE_TOKENS.has(token)) return true;
    if (FALSE_TOKENS.has(token)) return false;
  }
  return raw;
}

function toNumber(raw: unknown, integral = false): unknown {
  if (typeof raw === "boolean") return raw;
  if (typeof raw === "number") return integral ? Math.trunc(raw) : raw;
  if (typeof raw === "string" && raw.trim()) {
    const n = Number(raw.trim());
    if (!Number.isFinite(n)) return raw;
    return integral || Number.isInteger(n) ? Math.trunc(n) : n;
  }
  return raw;
}

// Trim, lower-case and de-duplicate — without folding, "Spam", "spam " and
// "spam" are three different labels and every agreement metric is noise.
function toTags(raw: unknown): unknown {
  const items = typeof raw === "string" ? raw.split(",") : Array.isArray(raw) ? raw : null;
  if (items === null) return raw;
  const out: string[] = [];
  for (const item of items) {
    if (typeof item !== "string") continue;
    const tag = item.trim().toLowerCase().split(/\s+/).join(" ");
    if (tag && !out.includes(tag)) out.push(tag);
  }
  return out;
}

// `ranking` — an ordered array; order is the answer, so nothing is sorted.
function toStringList(raw: unknown): unknown {
  return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === "string") : raw;
}

const BY_TYPE: Partial<Record<string, (raw: unknown) => unknown>> = {
  boolean: toBool,
  number: (raw) => toNumber(raw),
  slider: (raw) => toNumber(raw),
  rating: (raw) => toNumber(raw, true),
  likert: (raw) => toNumber(raw, true),
  tags: toTags,
  ranking: toStringList,
};

export function canonicalizeInput(
  input: InputField,
  raw: unknown,
  opts: { positionalVariant: string | null },
): unknown {
  const { positionalVariant } = opts;

  // choice_buttons under a panel_order variant → item canonicalization.
  if (input.type === "choice_buttons" && positionalVariant) {
    return canonicalizePositional(raw, positionalVariant);
  }

  // allow_other → strip the "other:" prefix.
  if (input.allow_other) {
    if (Array.isArray(raw)) return raw.map(stripOther);
    return stripOther(raw);
  }

  const converter = BY_TYPE[input.type];
  if (converter) return converter(raw);

  return raw;
}

export function canonicalize(
  schema: TemplateSchema,
  raw: Record<string, unknown>,
  positionalVariant: string | null,
): Record<string, unknown> {
  const value: Record<string, unknown> = {};
  const byId = new Map(schema.inputs.map((i) => [i.id, i]));
  for (const [id, rawVal] of Object.entries(raw)) {
    const input = byId.get(id);
    value[id] = input
      ? canonicalizeInput(input, rawVal, { positionalVariant })
      : rawVal;
  }
  return value;
}
