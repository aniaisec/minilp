// Pure schema operations behind the visual builder (§2.5, §11).
//
// The builder is a *second view* of the template document, not a second format:
// every operation here produces the same canonical schema (§2.1) the JSON editor
// validates and the backend stores. Keeping the operations pure is what lets the
// two views be swapped mid-edit without losing work — and lets them be tested
// without rendering anything.

import type {
  DisplayBlock,
  DisplayType,
  InputField,
  InputType,
  TemplateSchema,
} from "../../../api/types";

// --- palette ---------------------------------------------------------------

export interface PaletteEntry {
  type: InputType | DisplayType;
  label: string;
  hint: string;
}

export const INPUT_PALETTE: PaletteEntry[] = [
  { type: "radio", label: "Radio", hint: "one of a few options" },
  { type: "checkbox", label: "Checkboxes", hint: "many of a few options" },
  { type: "select", label: "Dropdown", hint: "one of many options" },
  { type: "multiselect", label: "Multi dropdown", hint: "many of many options" },
  { type: "choice_buttons", label: "Choice buttons", hint: "large keyed buttons" },
  { type: "likert", label: "Likert scale", hint: "labeled 1..N scale" },
  { type: "rating", label: "Rating", hint: "stars, a likert skin" },
  { type: "slider", label: "Slider", hint: "continuous number" },
  { type: "number", label: "Number", hint: "bounded numeric entry" },
  { type: "boolean", label: "Yes / no", hint: "two-state toggle" },
  { type: "free_text", label: "Free text", hint: "a typed answer" },
  { type: "tags", label: "Tags", hint: "free-form labels" },
  { type: "ranking", label: "Ranking", hint: "drag to order" },
  { type: "date", label: "Date", hint: "ISO date" },
  { type: "datetime", label: "Date & time", hint: "ISO datetime" },
];

export const DISPLAY_PALETTE: PaletteEntry[] = [
  { type: "text", label: "Text", hint: "plain passage" },
  { type: "markdown", label: "Markdown", hint: "formatted passage" },
  { type: "image", label: "Image", hint: "a picture to judge" },
  { type: "audio", label: "Audio", hint: "a clip to hear" },
  { type: "code", label: "Code", hint: "syntax-highlighted" },
  { type: "html_snippet", label: "HTML snippet", hint: "sandboxed markup" },
  { type: "panel_group", label: "Panels", hint: "N side-by-side panels" },
];

// --- defaults for a freshly dropped field ----------------------------------

/** A unique, schema-legal id derived from a type, e.g. `rating`, `rating_2`. */
export function uniqueId(base: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  const root = base.replace(/[^a-zA-Z0-9_]/g, "_").replace(/^[^a-zA-Z_]/, "f");
  if (!used.has(root)) return root;
  for (let n = 2; ; n++) {
    const candidate = `${root}_${n}`;
    if (!used.has(candidate)) return candidate;
  }
}

const NEEDS_OPTIONS = new Set<InputType>([
  "radio",
  "checkbox",
  "choice_buttons",
  "select",
  "multiselect",
  "ranking",
]);
const NEEDS_SCALE = new Set<InputType>(["likert", "rating"]);
const NEEDS_BOUNDS = new Set<InputType>(["slider"]);

/** A valid, immediately-renderable field of the requested type. */
export function newInput(type: InputType, taken: Iterable<string>): InputField {
  const field: InputField = {
    id: uniqueId(type, taken),
    type,
    label: defaultLabel(type),
    required: true,
  };
  if (NEEDS_OPTIONS.has(type)) field.options = ["Option A", "Option B"];
  if (NEEDS_SCALE.has(type)) field.scale = { min: 1, max: 5 };
  if (NEEDS_BOUNDS.has(type)) {
    field.min = 0;
    field.max = 1;
    field.step = 0.1;
  }
  if (type === "number") {
    field.min = 0;
    field.max = 100;
  }
  return field;
}

function defaultLabel(type: InputType): string {
  const entry = [...INPUT_PALETTE, ...DISPLAY_PALETTE].find((p) => p.type === type);
  return entry ? entry.label : type;
}

/** A valid display block of the requested type, sourced from a payload key. */
export function newDisplay(type: DisplayType, taken: Iterable<string>): DisplayBlock {
  const key = uniqueId(sourceStem(type), taken);
  if (type === "panel_group") {
    return { type, sources: [`$unit.${key}_a`, `$unit.${key}_b`], render: {} };
  }
  return { type, source: `$unit.${key}`, render: {} };
}

function sourceStem(type: DisplayType): string {
  if (type === "image") return "image_url";
  if (type === "audio") return "audio_url";
  if (type === "panel_group") return "response";
  return "text";
}

/** Payload keys a schema already references — so a new block doesn't collide. */
export function referencedKeys(schema: TemplateSchema): string[] {
  const keys: string[] = [];
  for (const block of schema.display ?? []) {
    const sources = [...(block.source ? [block.source] : []), ...(block.sources ?? [])];
    for (const s of sources) {
      const key = s.startsWith("$unit.") ? s.slice("$unit.".length) : s;
      if (!keys.includes(key)) keys.push(key);
    }
  }
  return keys;
}

// --- list operations (drag-and-drop reordering) -----------------------------

/** Move `from` to `to` in a copy of the list. Out-of-range indices are a no-op. */
export function moveItem<T>(list: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || from >= list.length || to < 0 || to >= list.length) {
    return list;
  }
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

export function removeAt<T>(list: T[], index: number): T[] {
  return list.filter((_, i) => i !== index);
}

export function replaceAt<T>(list: T[], index: number, item: T): T[] {
  return list.map((existing, i) => (i === index ? item : existing));
}

// --- a blank template -------------------------------------------------------

export function blankTemplate(name = "New template"): TemplateSchema {
  return {
    name,
    version: 1,
    description: "",
    layout: { arrangement: "stack", width: "lg" },
    display: [{ type: "text", source: "$unit.text", render: {} }],
    inputs: [
      {
        id: "verdict",
        type: "radio",
        label: "Verdict",
        options: ["Option A", "Option B"],
        required: true,
      },
    ],
    variants: null,
  };
}

/**
 * Strip builder-only emptiness before saving: an empty `render: {}` or a blank
 * description are noise in a stored document, and an empty string where the API
 * expects an omitted key is a validation error waiting to happen.
 */
export function cleanSchema(schema: TemplateSchema): TemplateSchema {
  const out: TemplateSchema = {
    ...schema,
    display: (schema.display ?? []).map((block) => {
      const copy: DisplayBlock = { ...block };
      if (copy.render && Object.keys(copy.render).length === 0) delete copy.render;
      if (!copy.optional) delete copy.optional;
      if (copy.source === undefined) delete copy.source;
      if (copy.sources === undefined) delete copy.sources;
      return copy;
    }),
    inputs: schema.inputs.map((field) => {
      const copy: InputField = { ...field };
      if (copy.help === "") delete copy.help;
      if (copy.label === "") delete copy.label;
      if (Array.isArray(copy.hotkeys) && copy.hotkeys.length === 0) delete copy.hotkeys;
      if (copy.hotkeys === "auto") delete copy.hotkeys;
      if (!copy.allow_other) delete copy.allow_other;
      return copy;
    }),
  };
  if (!out.description) delete out.description;
  if (!out.variants) out.variants = null;
  return out;
}
