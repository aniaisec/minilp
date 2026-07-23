// Template gallery (§11, M5): list the available templates, pick one, see how it
// actually works (the real annotation renderer, driven by editable sample data),
// and save that sample so the project wizard prefills it later.
//
// The preview reuses the Annotate component with a no-op client that keeps handing
// back the same sample unit — so "see how it works" is the genuine annotator
// experience (hotkeys, layout, Other box, Submit), not a mock of it.

import { useCallback, useEffect, useMemo, useState } from "react";

import type { MiniLpClient, TaskClient } from "../../api/client";
import type { LabelOut, Task, Template, TemplateSample } from "../../api/types";
import { Annotate } from "../Annotate";
import { Pill } from "./widgets";

// A client that always returns the same preview task and does nothing on submit /
// skip except re-serve it — so the renderer is fully interactive but inert.
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
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    async annotatorReport() {
      throw new Error("no report in preview");
    },
  };
}

function firstVariant(template: Template): Record<string, unknown> | null {
  const v = template.schema.variants;
  if (!v || !v.values?.length) return null;
  return { [v.dimension]: v.values[0] };
}

export function TemplateGallery({ client }: { client: MiniLpClient }) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [sample, setSample] = useState<TemplateSample | null>(null);
  const [sampleText, setSampleText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    client
      .listTemplates()
      .then((ts) => {
        setTemplates(ts);
        if (ts.length && selectedId === null) setSelectedId(ts[0].id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  useEffect(() => {
    if (selectedId === null) return;
    setSaveMsg(null);
    setParseError(null);
    client
      .getTemplateSample(selectedId)
      .then((s) => {
        setSample(s);
        setSampleText(JSON.stringify(s.sample, null, 2));
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [client, selectedId]);

  const selected = templates.find((t) => t.id === selectedId) ?? null;

  // Parsed sample payload driving the preview; falls back to last-good on a typo.
  const payload = useMemo<Record<string, unknown>>(() => {
    try {
      const obj = JSON.parse(sampleText);
      return obj && typeof obj === "object" ? obj : {};
    } catch {
      return sample?.sample ?? {};
    }
  }, [sampleText, sample]);

  const onSampleChange = useCallback((text: string) => {
    setSampleText(text);
    setSaveMsg(null);
    try {
      JSON.parse(text);
      setParseError(null);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : "invalid JSON");
    }
  }, []);

  const save = useCallback(async () => {
    if (selectedId === null || parseError) return;
    try {
      const parsed = JSON.parse(sampleText);
      const saved = await client.saveTemplateSample(selectedId, parsed);
      setSample(saved);
      setSaveMsg("Saved. The project wizard will prefill this sample.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [client, selectedId, sampleText, parseError]);

  const previewTask: Task | null = selected
    ? {
        slot_id: -1,
        unit_id: -1,
        project_id: -1,
        payload,
        variant: firstVariant(selected),
      }
    : null;

  return (
    <div className="mlp-gallery">
      <aside className="mlp-gallery-list mlp-card">
        <h3>Templates</h3>
        {error && <div className="mlp-error">{error}</div>}
        {templates.map((t) => (
          <button
            key={t.id}
            className={t.id === selectedId ? "mlp-gallery-item mlp-gallery-item-active" : "mlp-gallery-item"}
            onClick={() => setSelectedId(t.id)}
          >
            <span className="mlp-gallery-name">{t.name}</span>
            <Pill tone={t.kind === "builtin" ? "muted" : "ok"}>{t.kind}</Pill>
          </button>
        ))}
      </aside>

      <div className="mlp-gallery-main mlp-stack-lg">
        {selected && (
          <>
            <div className="mlp-card">
              <h3 style={{ marginTop: 0 }}>
                {selected.name} <span className="mlp-muted">v{selected.version}</span>
              </h3>
              {selected.description && <p className="mlp-muted">{selected.description}</p>}
              <details>
                <summary>
                  Sample data{" "}
                  {sample?.saved ? <Pill tone="ok">saved</Pill> : <Pill tone="muted">generated</Pill>}
                  {sample && (
                    <span className="mlp-muted" style={{ marginLeft: 8, fontSize: 12 }}>
                      required: {sample.fields.required.join(", ") || "none"}
                      {sample.fields.optional.length
                        ? ` · optional: ${sample.fields.optional.join(", ")}`
                        : ""}
                    </span>
                  )}
                </summary>
                <textarea
                  className="mlp-textarea mlp-mono"
                  rows={8}
                  value={sampleText}
                  onChange={(e) => onSampleChange(e.target.value)}
                />
                {parseError && <div className="mlp-error-text">JSON error: {parseError}</div>}
                <div className="mlp-actions" style={{ marginTop: 8 }}>
                  <button className="mlp-btn mlp-btn-primary" disabled={!!parseError} onClick={save}>
                    Save sample
                  </button>
                  {saveMsg && <span className="mlp-muted">{saveMsg}</span>}
                </div>
              </details>
            </div>

            <div className="mlp-card mlp-preview-frame">
              <div className="mlp-muted" style={{ marginBottom: 8 }}>
                Live preview — this is exactly what an annotator sees.
              </div>
              {previewTask && (
                <Annotate
                  // Remount when the schema or sample changes so the preview task refreshes.
                  key={`${selected.id}:${sampleText}`}
                  client={previewClient(previewTask)}
                  annotatorId={0}
                  projectId={0}
                  schema={selected.schema}
                  guidelines={selected.schema.description ?? ""}
                />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
