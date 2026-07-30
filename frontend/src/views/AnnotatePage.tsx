import { useEffect, useState } from "react";

import { MiniLpClient } from "../api/client";
import type { Project, Template } from "../api/types";
import { Annotate } from "./Annotate";
import { Home, homeUrl } from "./Home";
import { ReviewPage } from "./ReviewPage";

// Reads connection config from the URL (?project=&annotator=&key=), resolves the
// project's template, then hands the schema to the annotation loop.
//
// The three states this file switches between are the three routes an annotator
// has (M8, §11):
//   ?annotator=&key=            → home, a place you can return to
//   ?annotator=&key=&project=   → the annotation loop for that project
//   ?review=1&key=              → the reviewer's queue
function readConfig() {
  const q = new URLSearchParams(window.location.search);
  return {
    project: Number(q.get("project") ?? "0"),
    annotator: Number(q.get("annotator") ?? "0"),
    key: q.get("key") ?? "",
    review: q.get("review") === "1",
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

  // The reviewer's queue (M8, §7.2) — reachable without an annotator id, since
  // reviewing is not labeling.
  if (cfg.review) {
    return (
      <ReviewPage
        client={client}
        apiKey={cfg.key}
        projectId={cfg.project || undefined}
        homeHref={cfg.annotator ? homeUrl(cfg.annotator, cfg.key) : undefined}
      />
    );
  }

  // Annotator known but no project chosen → home (M8, §11).
  if (cfg.annotator && !cfg.project) {
    return <Home client={client} annotator={cfg.annotator} apiKey={cfg.key} />;
  }

  if (!cfg.annotator) {
    return (
      <div className="mlp-annotate" style={{ maxWidth: "var(--content-md)" }}>
        <div className="mlp-card">
          <h2>MiniLP — Annotate</h2>
          <p className="mlp-muted">
            Open with <code>?annotator=&lt;id&gt;&amp;key=&lt;api-key&gt;</code> to see your available
            tasks, or add <code>&amp;project=&lt;id&gt;</code> to jump straight into one.
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
      homeHref={homeUrl(cfg.annotator, cfg.key)}
    />
  );
}
