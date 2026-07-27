// Entry points 1 & 2 of the "one editor" (§2.5): create a template from scratch
// or from a clone, and edit an existing one.
//
// Editing follows the versioning rules the backend enforces (§2.5): a
// presentation-only change updates in place, a schema-affecting change lands as a
// new version. The editor doesn't decide which — it saves, and reports what the
// server did, so the rule lives in exactly one place.

import { useCallback, useEffect, useState } from "react";

import { ApiError, type MiniLpClient } from "../../../api/client";
import type { Template, TemplateSchema } from "../../../api/types";
import { TemplateBuilder } from "./TemplateBuilder";
import { blankTemplate, cleanSchema } from "./schema";

function errorList(e: unknown): string[] {
  if (e instanceof ApiError) {
    // The API returns {detail: {errors: [...]}} for validation failures.
    try {
      const parsed = JSON.parse(e.message) as { errors?: string[] };
      if (parsed.errors) return parsed.errors;
    } catch {
      /* not JSON — fall through */
    }
    return [e.message];
  }
  return [e instanceof Error ? e.message : String(e)];
}

export function TemplateEditor({
  client,
  templateId,
  onSaved,
}: {
  client: MiniLpClient;
  /** Omit to author from scratch. */
  templateId?: number;
  onSaved: (template: Template) => void;
}) {
  const [schema, setSchema] = useState<TemplateSchema>(() => blankTemplate());
  const [loaded, setLoaded] = useState(templateId === undefined);
  const [existing, setExisting] = useState<Template | null>(null);
  const [busy, setBusy] = useState(false);
  const [serverErrors, setServerErrors] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (templateId === undefined) return;
    client
      .getTemplate(templateId)
      .then((t) => {
        setExisting(t);
        setSchema(t.schema);
        setLoaded(true);
      })
      .catch((e) => setServerErrors(errorList(e)));
  }, [client, templateId]);

  const save = useCallback(async () => {
    setBusy(true);
    setServerErrors([]);
    setNote(null);
    try {
      const document = cleanSchema(schema);
      let saved: Template;
      if (existing && existing.kind !== "builtin") {
        saved = await client.updateTemplate(existing.id, document);
        setNote(
          saved.version === existing.version
            ? `Saved in place as v${saved.version} — a presentation-only edit doesn't bump the version (§2.5).`
            : `Saved as v${saved.version} — this edit changes stored values, so it became a new version (§2.5).`,
        );
      } else {
        // Builtins are immutable: "editing" one means cloning it first (§2.5).
        saved = await client.createTemplate(document);
        setNote(`Created “${saved.name}” v${saved.version}.`);
      }
      setExisting(saved);
      setSchema(saved.schema);
      onSaved(saved);
    } catch (e) {
      setServerErrors(errorList(e));
    } finally {
      setBusy(false);
    }
  }, [client, existing, schema, onSaved]);

  if (!loaded) return <div className="mlp-card">Loading template…</div>;

  return (
    <div className="mlp-stack-lg">
      <div>
        <h2 style={{ marginBottom: 4 }}>
          {existing ? `Edit “${existing.name}”` : "New template"}
        </h2>
        <p className="mlp-muted" style={{ marginTop: 0 }}>
          {existing?.kind === "builtin" ? (
            <>
              Gallery templates are immutable — saving creates an editable copy
              (§2.5 “clone is how you edit a builtin”).
            </>
          ) : (
            <>
              Drag fields onto the canvas or edit the JSON; both views write the
              same document. The preview is the real annotation renderer.
            </>
          )}
        </p>
      </div>

      {note && (
        <div className="mlp-card" data-testid="editor-note">
          {note}
        </div>
      )}

      <TemplateBuilder
        schema={schema}
        onChange={setSchema}
        onSave={save}
        busy={busy}
        serverErrors={serverErrors}
        saveLabel={existing && existing.kind !== "builtin" ? "Save template" : "Create template"}
      />
    </div>
  );
}
