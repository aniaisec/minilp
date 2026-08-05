// Entry point 3 of the "one editor" (§2.5, M6): edit a *live* project's config
// — guidelines, overlap K, agreement policy, gold ratio, thresholds — and, in the
// same surface, its template schema.
//
// Two things here are deliberate rather than incidental:
//
// - **Changing K reshapes the slot pool.** Raising it opens another balanced
//   round on every unfinished unit; lowering it is refused where work is already
//   collected. The panel says which happened rather than leaving you to diff the
//   progress view.
// - **A template edit clones and rebinds.** The project moves to a private copy;
//   whatever else was using that template is untouched. The panel names the new
//   template id so the change is traceable.

import { useCallback, useEffect, useState } from "react";

import { Button, Card, ErrorState } from "../../components/ui";
import { ApiError, type MiniLpClient } from "../../api/client";
import type { Project, ProjectPatch, Template, TemplateSchema } from "../../api/types";
import { TemplateBuilder } from "./builder/TemplateBuilder";
import { cleanSchema } from "./builder/schema";

function errorList(e: unknown): string[] {
  if (e instanceof ApiError) {
    try {
      const parsed = JSON.parse(e.message) as { errors?: string[] };
      if (parsed.errors) return parsed.errors;
    } catch {
      /* not JSON */
    }
    return [e.message];
  }
  return [e instanceof Error ? e.message : String(e)];
}

export function ConfigPanel({
  client,
  projectId,
}: {
  client: MiniLpClient;
  projectId: number;
}) {
  const [project, setProject] = useState<Project | null>(null);
  const [template, setTemplate] = useState<Template | null>(null);
  const [schema, setSchema] = useState<TemplateSchema | null>(null);
  const [form, setForm] = useState<ProjectPatch>({});
  const [agreementText, setAgreementText] = useState("");
  const [agreementError, setAgreementError] = useState<string | null>(null);
  const [editSchema, setEditSchema] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const p = await client.getProject(projectId);
      setProject(p);
      setForm({
        name: p.name,
        guidelines_md: p.guidelines_md ?? "",
        labels_per_unit: p.labels_per_unit,
        max_labels_per_unit: p.max_labels_per_unit,
        gold_ratio: p.gold_ratio,
      });
      const t = await client.getTemplate(p.template_id);
      setTemplate(t);
      setSchema(t.schema);
    } catch (e) {
      setErrors(errorList(e));
    }
  }, [client, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!project) return;
    setBusy(true);
    setErrors([]);
    setNote(null);
    try {
      const body: ProjectPatch = { ...form };
      if (agreementText.trim()) {
        try {
          body.agreement = JSON.parse(agreementText);
        } catch (e) {
          setAgreementError(e instanceof Error ? e.message : "invalid JSON");
          setBusy(false);
          return;
        }
      }
      if (editSchema && schema) body.template_schema = cleanSchema(schema);

      const result = await client.patchProject(project.id, body);
      setProject(result.project);
      const parts: string[] = ["Saved."];
      if (result.rebound) {
        parts.push(
          `The template was cloned and this project rebound to #${result.template_id} ` +
            `v${result.template_version} — nothing else using the old template changed (§2.5).`,
        );
      }
      if (result.slots_changed) {
        parts.push(
          `${result.slots_changed} slots ${
            (form.labels_per_unit ?? 0) >= (project.labels_per_unit ?? 0) ? "opened" : "removed"
          } to match the new overlap, in balanced rounds (§2.7).`,
        );
      }
      setNote(parts.join(" "));
      await load();
      setEditSchema(false);
    } catch (e) {
      setErrors(errorList(e));
    } finally {
      setBusy(false);
    }
  };

  if (!project) {
    return (
      <Card>
        {errors.length ? (
          <ErrorState title="Could not load this project" data-testid="config-load-error">
            {errors.join("; ")}
          </ErrorState>
        ) : (
          <p className="mlp-muted" role="status">
            Loading configuration…
          </p>
        )}
      </Card>
    );
  }

  const set = (patch: ProjectPatch) => setForm((f) => ({ ...f, ...patch }));

  return (
    <div className="mlp-stack-lg" data-testid="config-panel">
      {errors.length > 0 && (
        <Card>
          <ErrorState title="Configuration was not saved" data-testid="config-errors">
            <ul style={{ margin: 0, paddingLeft: 18, textAlign: "left" }}>
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </ErrorState>
        </Card>
      )}
      {note && (
        <div className="mlp-card" data-testid="config-note">
          {note}
        </div>
      )}

      <Card headingLevel={3} title="Project configuration">
        <label className="mlp-block-label">
          Name
          <input
            value={form.name ?? ""}
            data-testid="config-name"
            onChange={(e) => set({ name: e.target.value })}
          />
        </label>
        <label className="mlp-block-label">
          Annotator guidelines (markdown)
          <textarea
            className="mlp-textarea"
            rows={6}
            value={form.guidelines_md ?? ""}
            data-testid="config-guidelines"
            onChange={(e) => set({ guidelines_md: e.target.value })}
          />
        </label>
        <div className="mlp-grid-2">
          <label className="mlp-block-label">
            Labels per unit (K)
            <input
              type="number"
              min={1}
              value={form.labels_per_unit ?? 1}
              data-testid="config-k"
              onChange={(e) => set({ labels_per_unit: Number(e.target.value) })}
            />
          </label>
          <label className="mlp-block-label">
            Max labels per unit
            <input
              type="number"
              min={1}
              value={form.max_labels_per_unit ?? 1}
              data-testid="config-max-k"
              onChange={(e) => set({ max_labels_per_unit: Number(e.target.value) })}
            />
          </label>
          <label className="mlp-block-label">
            Gold ratio
            <input
              type="number"
              step={0.05}
              min={0}
              max={1}
              value={form.gold_ratio ?? 0}
              data-testid="config-gold-ratio"
              onChange={(e) => set({ gold_ratio: Number(e.target.value) })}
            />
          </label>
          <label className="mlp-block-label">
            Min reputation
            <input
              type="number"
              step={0.05}
              min={0}
              max={1}
              value={form.min_reputation ?? 0}
              data-testid="config-min-reputation"
              onChange={(e) => set({ min_reputation: Number(e.target.value) })}
            />
          </label>
        </div>
        <p className="mlp-muted mlp-field-hint">
          Raising K opens another balanced round of slots on every unfinished unit.
          Lowering it is refused once work has been collected — a labeled slot can't
          be retracted without either losing a label or breaking the K/n invariant
          (§2.7).
        </p>

        <label className="mlp-block-label">
          Agreement policy (JSON, per input key — leave blank to keep the current one)
          <textarea
            className="mlp-textarea mlp-mono"
            rows={4}
            placeholder={'{"category": {"match": "exact", "min_consensus": 0.67}}'}
            value={agreementText}
            data-testid="config-agreement"
            onChange={(e) => {
              setAgreementText(e.target.value);
              setAgreementError(null);
            }}
          />
        </label>
        {agreementError && (
          <ErrorState title="That is not valid JSON" inline data-testid="config-agreement-error">
            JSON error: {agreementError}
          </ErrorState>
        )}

        <div className="mlp-actions" style={{ marginTop: 12 }}>
          <Button
            variant="primary"
            disabled={busy}
            data-testid="config-save"
            onClick={() => void save()}
          >
            {busy ? "Saving…" : "Save configuration"}
          </Button>
        </div>
      </Card>

      <Card
        headingLevel={3}
        title="Template"
        description={
          <>
            Bound to <strong>{template?.name}</strong> v{project.template_version}. Editing the
            schema here clones the template and rebinds this project to the copy, so a template
            shared with other projects is never reshaped underneath them (§2.5).
          </>
        }
      >
        <label className="mlp-check">
          <input
            type="checkbox"
            checked={editSchema}
            data-testid="config-edit-schema"
            onChange={(e) => setEditSchema(e.target.checked)}
          />
          Edit this project's template
        </label>
        {editSchema && schema && (
          <div style={{ marginTop: 12 }}>
            <TemplateBuilder schema={schema} onChange={setSchema} showPreview />
            <p className="mlp-muted mlp-field-hint">
              Changes are applied by <strong>Save configuration</strong> above.
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}
