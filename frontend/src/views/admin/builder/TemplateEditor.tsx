// Entry points 1 & 2 of the "one editor" (§2.5): create a template from scratch
// or from a clone, and edit an existing one.
//
// Editing follows the versioning rules the backend enforces (§2.5): a
// presentation-only change updates in place, a schema-affecting change lands as a
// new version. The editor doesn't decide which — it saves, and reports what the
// server did, so the rule lives in exactly one place.

import { useCallback, useEffect, useState } from "react";

import { useToast } from "../../../components/Toast";
import { Card } from "../../../components/ui";
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
  const toast = useToast();
  const [schema, setSchema] = useState<TemplateSchema>(() => blankTemplate());
  const [loaded, setLoaded] = useState(templateId === undefined);
  const [existing, setExisting] = useState<Template | null>(null);
  const [busy, setBusy] = useState(false);
  const [serverErrors, setServerErrors] = useState<string[]>([]);

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

  // The versioning outcome is toasted, and this is the case that makes the
  // argument for toasts by itself: `onSaved` navigates away from the editor, so
  // the `<div data-testid="editor-note">` this replaces rendered into a
  // component that unmounted in the same commit. Nobody has ever read it. The
  // toast region lives in the shell, above the router, so it survives the
  // navigation the message is about.
  //
  // Which of the two things happened — an in-place edit or a new version — is
  // the server's decision (§2.5), and it is exactly the sort of thing an author
  // needs told rather than left to infer from a version number they were not
  // watching.
  const save = useCallback(async () => {
    setBusy(true);
    setServerErrors([]);
    try {
      const document = cleanSchema(schema);
      let saved: Template;
      if (existing && existing.kind !== "builtin") {
        saved = await client.updateTemplate(existing.id, document);
        toast.success(
          saved.version === existing.version
            ? `Saved in place as v${saved.version}.`
            : `Saved as a new version, v${saved.version}.`,
          saved.version === existing.version
            ? "A presentation-only edit doesn't bump the version (§2.5)."
            : "This edit changes stored values, so it became a new version (§2.5).",
        );
      } else {
        // Builtins are immutable: "editing" one means cloning it first (§2.5).
        saved = await client.createTemplate(document);
        toast.success(
          `Created “${saved.name}” v${saved.version}.`,
          existing?.kind === "builtin"
            ? "Gallery templates are immutable, so this saved as an editable copy."
            : undefined,
        );
      }
      setExisting(saved);
      setSchema(saved.schema);
      onSaved(saved);
    } catch (e) {
      // Stays inline: validation errors are a list of things to go and fix in
      // the canvas that is still on screen, not an announcement.
      setServerErrors(errorList(e));
    } finally {
      setBusy(false);
    }
  }, [client, existing, schema, onSaved, toast]);

  if (!loaded)
    return (
      <Card>
        <p className="mlp-muted" role="status">
          Loading template…
        </p>
      </Card>
    );

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
