// Template gallery (§11, M5): list the available templates, pick one, see how it
// actually works (the real annotation renderer, driven by editable sample data),
// and save that sample so the project wizard prefills it later.
//
// The preview reuses the Annotate component with a no-op client that keeps handing
// back the same sample unit — so "see how it works" is the genuine annotator
// experience (hotkeys, layout, Other box, Submit), not a mock of it.

import { useCallback, useEffect, useMemo, useState } from "react";

import type { MiniLpClient, TaskClient } from "../../api/client";
import type {
  LabelOut,
  Task,
  Template,
  TemplateSample,
  TemplateUsage,
} from "../../api/types";
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

// Delete, with the reason it can't be deleted shown *before* the click rather
// than after. The usage call is what makes that possible: a disabled button that
// says "in use by 'Q3 run' (#4)" is a different experience from a live button
// that 409s. Confirmation is a second click, not a modal — the operation is
// refused whenever it would lose data, so the only thing left to guard against
// is a misclick.
function DeleteTemplate({
  client,
  template,
  onDeleted,
}: {
  client: MiniLpClient;
  template: Template;
  onDeleted: (removedIds: number[]) => void;
}) {
  const [usage, setUsage] = useState<TemplateUsage | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [lineage, setLineage] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setConfirming(false);
    setLineage(false);
    setError(null);
    setUsage(null);
    client
      .getTemplateUsage(template.id)
      .then(setUsage)
      .catch(() => setUsage(null));
  }, [client, template.id]);

  const blockers = lineage ? (usage?.lineage_projects ?? []) : (usage?.projects ?? []);
  const blocked = blockers.length > 0;

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await client.deleteTemplate(template.id, lineage ? "all" : "one");
      onDeleted(result.deleted.map((d) => d.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="mlp-actions" style={{ gap: 8 }} data-testid="template-delete">
      {!confirming ? (
        <button
          className="mlp-btn mlp-btn-danger"
          data-testid="template-delete-start"
          disabled={blocked || usage === null}
          title={
            blocked
              ? `In use by ${blockers.map((b) => `'${b.name}' (#${b.project_id})`).join(", ")}`
              : "Delete this template version"
          }
          onClick={() => setConfirming(true)}
        >
          Delete
        </button>
      ) : (
        <>
          <span className="mlp-muted" data-testid="template-delete-prompt">
            Delete {lineage ? `all ${usage?.versions} versions of` : `v${template.version} of`}{" "}
            <strong>{template.name}</strong>?
          </span>
          <button
            className="mlp-btn mlp-btn-danger"
            data-testid="template-delete-confirm"
            disabled={busy || blocked}
            onClick={() => void run()}
          >
            {busy ? "Deleting…" : "Yes, delete"}
          </button>
          <button
            className="mlp-btn"
            data-testid="template-delete-cancel"
            onClick={() => setConfirming(false)}
          >
            Cancel
          </button>
        </>
      )}
      {(usage?.versions ?? 1) > 1 && (
        <label className="mlp-inline-label">
          <input
            type="checkbox"
            checked={lineage}
            data-testid="template-delete-lineage"
            onChange={(e) => setLineage(e.target.checked)}
          />
          all {usage?.versions} versions
        </label>
      )}
      {blocked && (
        <span className="mlp-muted" data-testid="template-delete-blocked" style={{ fontSize: 12 }}>
          In use by {blockers.map((b) => `${b.name} (#${b.project_id})`).join(", ")} — delete or
          rebind {blockers.length === 1 ? "that project" : "those projects"} first.
        </span>
      )}
      {error && (
        <span className="mlp-error-text" data-testid="template-delete-error">
          {error}
        </span>
      )}
    </span>
  );
}

function firstVariant(template: Template): Record<string, unknown> | null {
  const v = template.schema.variants;
  if (!v || !v.values?.length) return null;
  return { [v.dimension]: v.values[0] };
}

export function TemplateGallery({
  client,
  onNew,
  onEdit,
}: {
  client: MiniLpClient;
  /** Open the visual builder on a blank template (M6, §2.5). */
  onNew?: () => void;
  /** Open the visual builder on an existing template (M6, §2.5). */
  onEdit?: (templateId: number) => void;
}) {
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
        {onNew && (
          <button
            className="mlp-btn mlp-btn-primary"
            style={{ width: "100%", marginBottom: 10 }}
            data-testid="gallery-new"
            onClick={onNew}
          >
            + Build from scratch
          </button>
        )}
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
              {onEdit && (
                <div className="mlp-actions" style={{ marginBottom: 10 }}>
                  <button
                    className="mlp-btn"
                    data-testid="gallery-edit"
                    onClick={() => onEdit(selected.id)}
                  >
                    {selected.kind === "builtin" ? "Open in builder" : "Edit in builder"}
                  </button>
                  <button
                    className="mlp-btn"
                    data-testid="gallery-clone"
                    onClick={async () => {
                      try {
                        const copy = await client.cloneTemplate(selected.id);
                        setTemplates((ts) => [...ts, copy]);
                        setSelectedId(copy.id);
                        onEdit(copy.id);
                      } catch (e) {
                        setError(e instanceof Error ? e.message : String(e));
                      }
                    }}
                  >
                    Use as starting point
                  </button>
                  {selected.kind !== "builtin" && (
                    <DeleteTemplate
                      client={client}
                      template={selected}
                      onDeleted={(removedIds) => {
                        setTemplates((ts) => ts.filter((t) => !removedIds.includes(t.id)));
                        setSelectedId((id) => (id && removedIds.includes(id) ? null : id));
                      }}
                    />
                  )}
                  {selected.kind === "builtin" && (
                    <span className="mlp-muted" style={{ fontSize: 12 }}>
                      Gallery templates are immutable — saving from the builder
                      creates an editable copy (§2.5). They cannot be deleted.
                    </span>
                  )}
                </div>
              )}
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
                  // Inside the admin page: no second `<h1>`, no second `<main>`,
                  // no second skip link. The teal accent stays, because that is
                  // what an annotator sees.
                  embedded
                />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
