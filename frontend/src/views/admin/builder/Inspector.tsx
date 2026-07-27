// Inline editing for whatever is selected on the canvas (§11): a field's
// label / options / allow_other / required / hotkeys, or a block's source and
// render options. Every control writes straight into the schema document, so the
// JSON view and the preview update on the same keystroke.

import { useState } from "react";

import type {
  DisplayBlock,
  InputField,
  InputType,
  TemplateSchema,
} from "../../../api/types";

/**
 * A text control that keeps exactly what was typed.
 *
 * Fields like "options, one per line" derive their stored value by splitting and
 * dropping blanks — so rendering `options.join("\n")` back into the box swallows
 * the newline the moment you press Enter, and every option runs together. The
 * buffer keeps the literal text; the parsed value still flows out on every
 * keystroke, so validation and the preview stay live.
 */
function BufferedText({
  initial,
  onCommit,
  multiline,
  rows,
  placeholder,
  testId,
}: {
  initial: string;
  onCommit: (text: string) => void;
  multiline?: boolean;
  rows?: number;
  placeholder?: string;
  testId: string;
}) {
  const [text, setText] = useState(initial);
  const handle = (next: string) => {
    setText(next);
    onCommit(next);
  };
  return multiline ? (
    <textarea
      rows={rows}
      value={text}
      placeholder={placeholder}
      data-testid={testId}
      onChange={(e) => handle(e.target.value)}
    />
  ) : (
    <input
      type="text"
      value={text}
      placeholder={placeholder}
      data-testid={testId}
      onChange={(e) => handle(e.target.value)}
    />
  );
}

const splitLines = (text: string): string[] =>
  text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

const splitCommas = (text: string): string[] =>
  text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

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
// Types whose options carry hotkeys, so an explicit override is meaningful (§2.4).
const KEYED_TYPES = new Set<InputType>([
  "radio",
  "checkbox",
  "choice_buttons",
  "likert",
  "rating",
  "boolean",
]);

const RENDER_OPTIONS: Record<string, { key: string; kind: "bool" | "text" | "number" }[]> = {
  text: [
    { key: "collapsible", kind: "bool" },
    { key: "max_lines", kind: "number" },
  ],
  markdown: [
    { key: "collapsible", kind: "bool" },
    { key: "max_lines", kind: "number" },
  ],
  image: [
    { key: "fit", kind: "text" },
    { key: "zoom", kind: "bool" },
    { key: "lightbox", kind: "bool" },
  ],
  audio: [
    { key: "waveform", kind: "bool" },
    { key: "playback_speed", kind: "bool" },
  ],
  code: [
    { key: "language", kind: "text" },
    { key: "line_numbers", kind: "bool" },
  ],
  html_snippet: [],
  panel_group: [
    { key: "sync_scroll", kind: "bool" },
    { key: "diff_highlight", kind: "bool" },
  ],
};

export function InputInspector({
  field,
  onChange,
}: {
  field: InputField;
  onChange: (next: InputField) => void;
}) {
  const set = (patch: Partial<InputField>) => onChange({ ...field, ...patch });
  const options = field.options ?? [];

  return (
    <div className="mlp-inspector" data-testid="inspector-input">
      <label>
        Key (stored as the answer's key)
        <input
          type="text"
          value={field.id}
          data-testid="inspector-id"
          onChange={(e) => set({ id: e.target.value })}
        />
      </label>
      <label>
        Label
        <input
          type="text"
          value={field.label ?? ""}
          data-testid="inspector-label"
          onChange={(e) => set({ label: e.target.value })}
        />
      </label>
      <label>
        Help text
        <input
          type="text"
          value={field.help ?? ""}
          data-testid="inspector-help"
          onChange={(e) => set({ help: e.target.value })}
        />
      </label>
      <label className="mlp-check">
        <input
          type="checkbox"
          checked={!!field.required}
          data-testid="inspector-required"
          onChange={(e) => set({ required: e.target.checked })}
        />
        Required (gates submission, §2.3)
      </label>

      {ALLOW_OTHER_TYPES.has(field.type) && (
        <label className="mlp-check">
          <input
            type="checkbox"
            checked={!!field.allow_other}
            data-testid="inspector-allow-other"
            onChange={(e) => set({ allow_other: e.target.checked })}
          />
          Allow “Other…” (free-text escape hatch, key <code>o</code>)
        </label>
      )}

      {OPTION_TYPES.has(field.type) && (
        <label>
          Options (one per line)
          <BufferedText
            multiline
            rows={Math.max(3, options.length + 1)}
            initial={options.join("\n")}
            testId="inspector-options"
            onCommit={(text) => set({ options: splitLines(text) })}
          />
        </label>
      )}

      {SCALE_TYPES.has(field.type) && (
        <div className="mlp-grid-2">
          <label>
            Scale min
            <input
              type="number"
              value={field.scale?.min ?? 1}
              data-testid="inspector-scale-min"
              onChange={(e) => set({ scale: { ...field.scale, min: Number(e.target.value) } })}
            />
          </label>
          <label>
            Scale max
            <input
              type="number"
              value={field.scale?.max ?? 5}
              data-testid="inspector-scale-max"
              onChange={(e) => set({ scale: { ...field.scale, max: Number(e.target.value) } })}
            />
          </label>
        </div>
      )}

      {RANGE_TYPES.has(field.type) && (
        <div className="mlp-grid-2">
          <label>
            Min
            <input
              type="number"
              value={field.min ?? ""}
              data-testid="inspector-min"
              onChange={(e) =>
                set({ min: e.target.value === "" ? undefined : Number(e.target.value) })
              }
            />
          </label>
          <label>
            Max
            <input
              type="number"
              value={field.max ?? ""}
              data-testid="inspector-max"
              onChange={(e) =>
                set({ max: e.target.value === "" ? undefined : Number(e.target.value) })
              }
            />
          </label>
          <label>
            Step
            <input
              type="number"
              value={field.step ?? ""}
              data-testid="inspector-step"
              onChange={(e) =>
                set({ step: e.target.value === "" ? undefined : Number(e.target.value) })
              }
            />
          </label>
        </div>
      )}

      {KEYED_TYPES.has(field.type) && (
        <label>
          Hotkeys — blank for auto (§2.4), else one key per option, comma separated
          <BufferedText
            placeholder="auto"
            initial={Array.isArray(field.hotkeys) ? field.hotkeys.join(", ") : ""}
            testId="inspector-hotkeys"
            onCommit={(text) => {
              const keys = splitCommas(text);
              set({ hotkeys: keys.length ? keys : "auto" });
            }}
          />
        </label>
      )}
    </div>
  );
}

export function DisplayInspector({
  block,
  onChange,
}: {
  block: DisplayBlock;
  onChange: (next: DisplayBlock) => void;
}) {
  const set = (patch: Partial<DisplayBlock>) => onChange({ ...block, ...patch });
  const renderOpts = RENDER_OPTIONS[block.type] ?? [];
  const render = block.render ?? {};

  return (
    <div className="mlp-inspector" data-testid="inspector-display">
      {block.type === "panel_group" ? (
        <label>
          Panel sources (one <code>$unit.key</code> per line, in item order A, B, …)
          <BufferedText
            multiline
            rows={3}
            initial={(block.sources ?? []).join("\n")}
            testId="inspector-sources"
            onCommit={(text) => set({ sources: splitLines(text) })}
          />
        </label>
      ) : (
        <label>
          Source (a <code>$unit.key</code> from the unit payload)
          <input
            type="text"
            value={block.source ?? ""}
            data-testid="inspector-source"
            onChange={(e) => set({ source: e.target.value })}
          />
        </label>
      )}

      <label className="mlp-check">
        <input
          type="checkbox"
          checked={!!block.optional}
          data-testid="inspector-optional"
          onChange={(e) => set({ optional: e.target.checked })}
        />
        Optional (units without this field still validate)
      </label>

      {renderOpts.map((opt) => (
        <label key={opt.key} className={opt.kind === "bool" ? "mlp-check" : undefined}>
          {opt.kind === "bool" ? (
            <>
              <input
                type="checkbox"
                checked={!!render[opt.key]}
                data-testid={`inspector-render-${opt.key}`}
                onChange={(e) => {
                  const next = { ...render };
                  if (e.target.checked) next[opt.key] = true;
                  else delete next[opt.key];
                  set({ render: next });
                }}
              />
              {opt.key}
            </>
          ) : (
            <>
              {opt.key}
              <input
                type={opt.kind === "number" ? "number" : "text"}
                value={(render[opt.key] as string | number) ?? ""}
                data-testid={`inspector-render-${opt.key}`}
                onChange={(e) => {
                  const next = { ...render };
                  if (e.target.value === "") delete next[opt.key];
                  else next[opt.key] = opt.kind === "number" ? Number(e.target.value) : e.target.value;
                  set({ render: next });
                }}
              />
            </>
          )}
        </label>
      ))}
    </div>
  );
}

export function LayoutInspector({
  schema,
  onChange,
}: {
  schema: TemplateSchema;
  onChange: (next: TemplateSchema) => void;
}) {
  const layout = schema.layout ?? {};
  const setLayout = (patch: Record<string, unknown>) =>
    onChange({ ...schema, layout: { ...layout, ...patch } });

  return (
    <div className="mlp-inspector" data-testid="inspector-layout">
      <label>
        Template name
        <input
          type="text"
          value={schema.name}
          data-testid="builder-name"
          onChange={(e) => onChange({ ...schema, name: e.target.value })}
        />
      </label>
      <label>
        Description
        <input
          type="text"
          value={schema.description ?? ""}
          data-testid="builder-description"
          onChange={(e) => onChange({ ...schema, description: e.target.value })}
        />
      </label>
      <div className="mlp-grid-2">
        <label>
          Arrangement
          <select
            value={layout.arrangement ?? "stack"}
            data-testid="builder-arrangement"
            onChange={(e) =>
              setLayout({ arrangement: e.target.value as "stack" | "split" | "columns" })
            }
          >
            <option value="stack">stack</option>
            <option value="split">split</option>
            <option value="columns">columns</option>
          </select>
        </label>
        <label>
          Width
          <select
            value={layout.width ?? "lg"}
            data-testid="builder-width"
            onChange={(e) => setLayout({ width: e.target.value as "md" | "lg" | "xl" | "full" })}
          >
            <option value="md">md</option>
            <option value="lg">lg</option>
            <option value="xl">xl</option>
            <option value="full">full</option>
          </select>
        </label>
      </div>
      <p className="mlp-muted" style={{ fontSize: 12 }}>
        Layout and render options are presentation-only — changing them never bumps
        the template version or invalidates collected labels (§2.2, §2.5).
      </p>
    </div>
  );
}
