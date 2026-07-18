import { useEffect, useState } from "react";

import { MiniLpClient } from "../api/client";
import type { Project, Template } from "../api/types";
import { Annotate } from "./Annotate";

// Reads connection config from the URL (?project=&annotator=&key=), resolves the
// project's template, then hands the schema to the annotation loop.
function readConfig() {
  const q = new URLSearchParams(window.location.search);
  return {
    project: Number(q.get("project") ?? "0"),
    annotator: Number(q.get("annotator") ?? "0"),
    key: q.get("key") ?? "",
  };
}

export function AnnotatePage() {
  const [cfg] = useState(readConfig);
  const [project, setProject] = useState<Project | null>(null);
  const [template, setTemplate] = useState<Template | null>(null);
  const [error, setError] = useState<string | null>(null);

  const client = new MiniLpClient({ apiKey: cfg.key || undefined });

  useEffect(() => {
    if (!cfg.project || !cfg.annotator) return;
    (async () => {
      try {
        const p = await client.getProject(cfg.project);
        setProject(p);
        const t = await client.getTemplate(p.template_id);
        setTemplate(t);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cfg.project, cfg.annotator]);

  if (!cfg.project || !cfg.annotator) {
    return (
      <div className="mlp-annotate" style={{ maxWidth: "var(--content-md)" }}>
        <div className="mlp-card">
          <h2>MiniLP — Annotate</h2>
          <p className="mlp-muted">
            Open with <code>?project=&lt;id&gt;&amp;annotator=&lt;id&gt;&amp;key=&lt;api-key&gt;</code>
            to start labeling.
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mlp-annotate" style={{ maxWidth: "var(--content-md)" }}>
        <div className="mlp-card" style={{ borderColor: "var(--danger)" }}>
          {error}
        </div>
      </div>
    );
  }

  if (!project || !template) {
    return (
      <div className="mlp-annotate" style={{ maxWidth: "var(--content-md)" }}>
        <div className="mlp-card">Loading project…</div>
      </div>
    );
  }

  return (
    <Annotate
      client={client}
      annotatorId={cfg.annotator}
      projectId={cfg.project}
      schema={template.schema}
      guidelines={project.guidelines_md ?? ""}
    />
  );
}
