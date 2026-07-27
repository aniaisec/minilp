// Client-side template validation for the builder's live feedback (§2.5).
//
// **The backend is authoritative.** This is a port of the rules in
// `services/templates/validation.py` chosen for the ones an author trips over
// while dragging fields around — a missing option, a bad bound, a hotkey clash —
// so the error appears as you type instead of after a round trip. Save still goes
// through the server, and a server error is shown verbatim: if the two ever
// disagree, the server wins and the author sees why.

import type { InputType, TemplateSchema } from "../../../api/types";
import { assignHotkeys } from "../../../hotkeys/assign";

const OPTION_TYPES = new Set<InputType>([
  "radio",
  "checkbox",
  "choice_buttons",
  "select",
  "multiselect",
  "ranking",
]);
const ALLOW_OTHER_TYPES = new Set<InputType>(["radio", "checkbox", "select", "multiselect"]);
const SCALE_TYPES = new Set<InputType>(["likert", "rating"]);
const RANGE_TYPES = new Set<InputType>(["number", "slider"]);
const BOUNDS_REQUIRED = new Set<InputType>(["slider"]);

const ID_PATTERN = /^[a-zA-Z_][a-zA-Z0-9_]*$/;
const UNIT_REF = "$unit.";

const RENDER_OPTIONS: Record<string, string[]> = {
  text: ["collapsible", "max_lines"],
  markdown: ["collapsible", "max_lines"],
  image: ["fit", "zoom", "lightbox"],
  audio: ["waveform", "playback_speed"],
  code: ["language", "line_numbers"],
  html_snippet: [],
  panel_group: ["sync_scroll", "diff_highlight"],
};

export function validateSchema(schema: TemplateSchema): string[] {
  const errors: string[] = [];

  if (!schema.name || !schema.name.trim()) errors.push("template needs a name");
  if (!schema.inputs || schema.inputs.length === 0) {
    errors.push("template needs at least one input");
  }

  const seen = new Set<string>();
  for (const field of schema.inputs ?? []) {
    const id = field.id ?? "";
    if (!ID_PATTERN.test(id)) {
      errors.push(`input id '${id}' must start with a letter or _ and contain only letters, digits, _`);
    }
    if (seen.has(id)) errors.push(`duplicate input id '${id}'`);
    seen.add(id);

    const options = field.options ?? [];
    if (OPTION_TYPES.has(field.type)) {
      if (options.length < 2) errors.push(`input '${id}' (${field.type}) needs at least 2 options`);
      if (new Set(options).size !== options.length) {
        errors.push(`input '${id}' has duplicate options`);
      }
    } else if (options.length) {
      errors.push(`input '${id}' (${field.type}) must not declare options`);
    }

    if (field.allow_other && !ALLOW_OTHER_TYPES.has(field.type)) {
      errors.push(`input '${id}' (${field.type}) does not support allow_other`);
    }

    if (SCALE_TYPES.has(field.type)) {
      const scale = field.scale ?? {};
      if (!scale.labels && (scale.max ?? 5) <= (scale.min ?? 1)) {
        errors.push(`input '${id}' ${field.type} scale max must exceed min`);
      }
    } else if (field.scale) {
      errors.push(`input '${id}' (${field.type}) must not declare a scale`);
    }

    const { min, max, step } = field;
    if (!RANGE_TYPES.has(field.type)) {
      for (const [name, present] of [["min", min], ["max", max], ["step", step]] as const) {
        if (present !== undefined) {
          errors.push(`input '${id}' (${field.type}) must not declare ${name}`);
        }
      }
    } else {
      if (BOUNDS_REQUIRED.has(field.type) && (min === undefined || max === undefined)) {
        errors.push(`input '${id}' (${field.type}) requires both min and max`);
      }
      if (min !== undefined && max !== undefined && max <= min) {
        errors.push(`input '${id}' (${field.type}) max must exceed min`);
      }
      if (step !== undefined && step <= 0) errors.push(`input '${id}' step must be positive`);
      if (step !== undefined && min !== undefined && max !== undefined && step > max - min) {
        errors.push(`input '${id}' (${field.type}) step is larger than its range`);
      }
    }
  }

  (schema.display ?? []).forEach((block, i) => {
    const sources = [...(block.source ? [block.source] : []), ...(block.sources ?? [])];
    if (block.type !== "panel_group" && sources.length === 0) {
      errors.push(`display[${i}] (${block.type}) requires a source`);
    }
    for (const source of sources) {
      if (!source.startsWith(UNIT_REF)) {
        errors.push(`display[${i}] source '${source}' must be a $unit.<key> reference`);
      }
    }
    const allowed = RENDER_OPTIONS[block.type] ?? [];
    for (const key of Object.keys(block.render ?? {})) {
      if (!allowed.includes(key)) {
        errors.push(
          `display[${i}] (${block.type}) render option '${key}' is not valid ` +
            `(allowed: ${allowed.join(", ") || "none"})`,
        );
      }
    }
  });

  const layout = schema.layout ?? {};
  if (layout.arrangement === "split" && layout.ratio && layout.ratio.length !== 2) {
    errors.push("layout.ratio must have exactly 2 entries for a split arrangement");
  }

  if (schema.variants) {
    const values = schema.variants.values ?? [];
    if (values.length < 2) errors.push("variants need at least 2 values");
    if (new Set(values).size !== values.length) errors.push("variants.values must be unique");
  }

  // Hotkey conflicts, using the same assignment the renderer draws badges from —
  // so an error here means the badge you'd have seen was impossible (§2.4).
  if ((schema.inputs ?? []).length && !errors.some((e) => e.includes("at least 2 options"))) {
    errors.push(...assignHotkeys(schema.inputs).errors);
  }

  return errors;
}
