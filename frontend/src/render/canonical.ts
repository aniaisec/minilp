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
