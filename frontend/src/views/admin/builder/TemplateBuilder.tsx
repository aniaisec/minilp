// The visual template builder (§2.5, §11, M6).
//
// Two synced views of *one* document: a drag-and-drop canvas and a JSON editor.
// Switching between them never loses work because both edit the same
// `TemplateSchema` object — the JSON view is a serialization of the state the
// canvas manipulates, not a separate format. Beside them is the live preview:
// the real annotation renderer, driven by a sample payload, so layout, hotkey
// badges and the `?` overlay are all exactly what an annotator will get.
//
// This component is the "one editor" of §2.5. It knows how to *edit a schema*;
// the three entry points (create a template, edit a template, edit a project's
// config) supply the schema and decide what Save means.

import { useMemo, useState } from "react";

import type {
  DisplayType,
  InputType,
  LabelOut,
  Task,
  TemplateSchema,
} from "../../../api/types";
import type { TaskClient } from "../../../api/client";
import { Annotate } from "../../Annotate";
import { Canvas, PaletteButton } from "./Canvas";
import { DisplayInspector, InputInspector, LayoutInspector } from "./Inspector";
import {
  DISPLAY_PALETTE,
  INPUT_PALETTE,
  cleanSchema,
  moveItem,
  newDisplay,
  newInput,
  referencedKeys,
  removeAt,
  replaceAt,
} from "./schema";
import { validateSchema } from "./validate";

type Selection = { kind: "display" | "input"; index: number } | { kind: "layout" } | null;
type View = "builder" | "json";

// An inert client that hands the preview the same sample task forever.
function previewClient(task: Task): TaskClient {
  return {
    nextTask: async () => task,
    submit: async (): Promise<LabelOut> => ({
      id: 0,
      slot_id: task.slot_id,
      unit_id: task.unit_id,
      annotator_id: 0,
      value: {},
      is_valid: true,
    }),
    skip: async () => ({ slot_id: task.slot_id, status: "open" }),
  };
}

/** A sample payload covering every `$unit.` key the schema references. */
export function samplePayloadFor(schema: TemplateSchema): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const block of schema.display ?? []) {
    const sources = [...(block.source ? [block.source] : []), ...(block.sources ?? [])];
    for (const source of sources) {
      const key = source.startsWith("$unit.") ? source.slice("$unit.".length) : source;
      if (block.type === "image") payload[key] = "https://placehold.co/480x320?text=sample";
      else if (block.type === "audio") payload[key] = "https://example.com/sample.mp3";
      else if (block.type === "code") payload[key] = "def greet(name):\n    return name";
      else if (block.type === "html_snippet") payload[key] = "<p>Example snippet.</p>";
      else payload[key] = `Example ${key.replace(/_/g, " ")}.`;
    }
  }
  return payload;
}

export interface TemplateBuilderProps {
  schema: TemplateSchema;
  onChange: (next: TemplateSchema) => void;
  /** Save handler; the caller decides whether that's a POST, a PUT or a PATCH. */
  onSave?: () => void | Promise<void>;
  saveLabel?: string;
  busy?: boolean;
  /** Errors the *server* rejected the schema with — shown verbatim above ours. */
  serverErrors?: string[];
  /** Hide the preview when the surrounding page already shows one. */
  showPreview?: boolean;
}

export function TemplateBuilder({
  schema,
  onChange,
  onSave,
  saveLabel = "Save template",
  busy = false,
  serverErrors = [],
  showPreview = true,
}: TemplateBuilderProps) {
  const [view, setView] = useState<View>("builder");
  const [selection, setSelection] = useState<Selection>({ kind: "layout" });
  const [jsonText, setJsonText] = useState(() => JSON.stringify(schema, null, 2));
  const [jsonError, setJsonError] = useState<string | null>(null);

  const errors = useMemo(() => validateSchema(schema), [schema]);
  const payload = useMemo(() => samplePayloadFor(schema), [schema]);
  const inputs = schema.inputs ?? [];
  const display = schema.display ?? [];

  // Switching to JSON re-serializes from the live document, so the two views can
  // never drift: the canvas is always the thing being serialized.
  const showJson = () => {
    setJsonText(JSON.stringify(schema, null, 2));
    setJsonError(null);
    setView("json");
  };

  const applyJson = (text: string) => {
    setJsonText(text);
    try {
      const parsed = JSON.parse(text);
      setJsonError(null);
      onChange(parsed as TemplateSchema);
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : "invalid JSON");
    }
  };

  const addInput = (type: string) => {
    const field = newInput(type as InputType, inputs.map((i) => i.id));
    onChange({ ...schema, inputs: [...inputs, field] });
    setSelection({ kind: "input", index: inputs.length });
  };

  const addDisplay = (type: string) => {
    const block = newDisplay(type as DisplayType, referencedKeys(schema));
    onChange({ ...schema, display: [...display, block] });
    setSelection({ kind: "display", index: display.length });
  };

  const reorder = (kind: "display" | "input", from: number, to: number) => {
    if (kind === "input") {
      const moved = moveItem(inputs, from, to);
      if (moved === inputs) return;
      onChange({ ...schema, inputs: moved });
    } else {
      const moved = moveItem(display, from, to);
      if (moved === display) return;
      onChange({ ...schema, display: moved });
    }
    if (selection && selection.kind === kind && selection.index === from) {
      setSelection({ kind, index: to });
    }
  };

  const remove = (kind: "display" | "input", index: number) => {
    if (kind === "input") onChange({ ...schema, inputs: removeAt(inputs, index) });
    else onChange({ ...schema, display: removeAt(display, index) });
    setSelection({ kind: "layout" });
  };

  const previewTask: Task = {
    slot_id: -1,
    unit_id: -1,
    project_id: -1,
    payload,
    variant: schema.variants?.values?.length
      ? { [schema.variants.dimension]: schema.variants.values[0] }
      : null,
  };

  return (
    <div className="mlp-stack-lg">
      <div className="mlp-actions" style={{ justifyContent: "space-between" }}>
        <div className="mlp-view-toggle" role="group" aria-label="Editor view">
          <button
            type="button"
            aria-pressed={view === "builder"}
            data-testid="view-builder"
            onClick={() => setView("builder")}
          >
            Builder
          </button>
          <button
            type="button"
            aria-pressed={view === "json"}
            data-testid="view-json"
            onClick={showJson}
          >
            JSON
          </button>
        </div>
        {onSave && (
          <button
            type="button"
            className="mlp-btn mlp-btn-primary"
            disabled={busy || errors.length > 0 || !!jsonError}
            data-testid="builder-save"
            onClick={() => void onSave()}
          >
            {busy ? "Saving…" : saveLabel}
          </button>
        )}
      </div>

      {(errors.length > 0 || serverErrors.length > 0 || jsonError) && (
        <div className="mlp-card mlp-builder-errors" data-testid="builder-errors">
          <strong>
            {serverErrors.length ? "The server rejected this template" : "Not valid yet"}
          </strong>
          <ul>
            {jsonError && <li>JSON: {jsonError}</li>}
            {serverErrors.map((e) => (
              <li key={`s:${e}`}>{e}</li>
            ))}
            {errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      <div
        className={
          showPreview ? "mlp-builder-shell mlp-builder-shell-split" : "mlp-builder-shell"
        }
        data-testid="builder-shell"
      >
        <div className="mlp-builder-work">
          {view === "json" ? (
            <div className="mlp-card">
              <p className="mlp-muted" style={{ marginTop: 0 }}>
                The same document the builder edits. Switch back and your changes are
                there — these are two views, not two formats (§2.5).
              </p>
              <textarea
                className="mlp-textarea mlp-mono"
                rows={26}
                value={jsonText}
                data-testid="builder-json"
                onChange={(e) => applyJson(e.target.value)}
              />
            </div>
          ) : (
            <div className="mlp-builder">
              <aside className="mlp-card mlp-palette mlp-builder-palette">
                <h4>Display blocks</h4>
                {DISPLAY_PALETTE.map((entry) => (
                  <PaletteButton key={entry.type} {...entry} onAdd={addDisplay} />
                ))}
                <h4>Input fields</h4>
                {INPUT_PALETTE.map((entry) => (
                  <PaletteButton key={entry.type} {...entry} onAdd={addInput} />
                ))}
              </aside>

              <section className="mlp-card mlp-builder-canvas">
                <h3 style={{ marginTop: 0 }}>Canvas</h3>
                <button
                  type="button"
                  className="mlp-btn mlp-btn-tiny"
                  data-testid="select-layout"
                  onClick={() => setSelection({ kind: "layout" })}
                >
                  Template & layout settings
                </button>

                <h4 className="mlp-muted" style={{ marginBottom: 4 }}>
                  What the annotator sees
                </h4>
                <Canvas
                  testId="canvas-display"
                  items={display.map((block, i) => ({
                    key: `d${i}:${block.type}`,
                    title: block.sources ? block.sources.join(" · ") : (block.source ?? "(no source)"),
                    type: block.type,
                  }))}
                  selected={selection?.kind === "display" ? selection.index : null}
                  emptyHint="Drag a display block here (or click one in the palette)."
                  onSelect={(index) => setSelection({ kind: "display", index })}
                  onReorder={(from, to) => reorder("display", from, to)}
                  onDropNew={addDisplay}
                  onRemove={(index) => remove("display", index)}
                />

                <h4 className="mlp-muted" style={{ marginBottom: 4 }}>
                  What they answer
                </h4>
                <Canvas
                  testId="canvas-inputs"
                  items={inputs.map((field, i) => ({
                    key: `i${i}:${field.id}`,
                    title: `${field.label || field.id}${field.required ? " *" : ""}`,
                    type: field.type,
                  }))}
                  selected={selection?.kind === "input" ? selection.index : null}
                  emptyHint="Drag an input field here (or click one in the palette)."
                  onSelect={(index) => setSelection({ kind: "input", index })}
                  onReorder={(from, to) => reorder("input", from, to)}
                  onDropNew={addInput}
                  onRemove={(index) => remove("input", index)}
                />
                <p className="mlp-muted mlp-field-hint">
                  Drag to reorder, or focus a row and press Alt+↑ / Alt+↓.
                </p>
              </section>

              <section className="mlp-card mlp-builder-inspector">
                <h3 style={{ marginTop: 0 }}>
                  {selection?.kind === "input"
                    ? "Field"
                    : selection?.kind === "display"
                      ? "Block"
                      : "Template"}
                </h3>
                {selection?.kind === "input" && inputs[selection.index] && (
                  <InputInspector
                    key={`i${selection.index}`}
                    field={inputs[selection.index]}
                    onChange={(next) =>
                      onChange({ ...schema, inputs: replaceAt(inputs, selection.index, next) })
                    }
                  />
                )}
                {selection?.kind === "display" && display[selection.index] && (
                  <DisplayInspector
                    key={`d${selection.index}`}
                    block={display[selection.index]}
                    onChange={(next) =>
                      onChange({ ...schema, display: replaceAt(display, selection.index, next) })
                    }
                  />
                )}
                {(!selection || selection.kind === "layout") && (
                  <LayoutInspector schema={schema} onChange={onChange} />
                )}
              </section>
            </div>
          )}
        </div>

        {showPreview && (
          // The preview is a *column*, not a footer: on a wide window it sits
          // beside the canvas and sticks while you scroll, so the thing you are
          // building stays on screen the whole time you build it. Below the
          // breakpoint the shell collapses to one column and this lands at the
          // bottom — the layout rule is in CSS, so there is no JS resize
          // listener and no state to get out of sync with the window.
          <aside className="mlp-builder-preview" data-testid="builder-preview">
            <div className="mlp-card mlp-preview-frame">
              <div className="mlp-muted" style={{ marginBottom: 8 }}>
                Live preview — the real annotation renderer, on a generated sample unit.
              </div>
              {errors.length === 0 ? (
                <Annotate
                  key={JSON.stringify(schema)}
                  client={previewClient(previewTask)}
                  annotatorId={0}
                  projectId={0}
                  schema={cleanSchema(schema)}
                  guidelines={schema.description ?? ""}
                />
              ) : (
                <p className="mlp-muted">Fix the errors listed above to see the preview.</p>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
