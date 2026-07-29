// Admin dashboard (§11): the project list, entry point to the wizard and to each
// project's progress/analytics.

import { useEffect, useState } from "react";

import type { MiniLpClient } from "../../api/client";
import type { ProjectSummary } from "../../api/types";
import { StartLabeling } from "./StartLabeling";

export function Dashboard({
  client,
  apiKey,
  onOpen,
  onNew,
}: {
  client: MiniLpClient;
  /** Carried into the annotation-view URL so "Start labeling" needs no re-auth. */
  apiKey: string;
  onOpen: (id: number) => void;
  onNew: () => void;
}) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    client
      .listProjects()
      .then(setProjects)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [client]);

  return (
    <div className="mlp-stack-lg" style={{ maxWidth: "var(--content-xl)" }}>
      <div className="mlp-actions" style={{ justifyContent: "space-between" }}>
        <h2>Projects</h2>
        <button className="mlp-btn mlp-btn-primary" onClick={onNew}>
          + New project
        </button>
      </div>
      {error && <div className="mlp-card mlp-error">{error}</div>}
      {!projects && !error && <div className="mlp-card">Loading…</div>}
      {projects && projects.length === 0 && (
        <div className="mlp-card mlp-muted">No projects yet — create one to get started.</div>
      )}
      <div className="mlp-project-grid">
        {projects?.map((p) => (
          // A div, not a button: the card now contains its own button, and a
          // button inside a button is invalid HTML that browsers resolve by
          // dropping one of them — usually the one you wanted.
          <div
            key={p.id}
            className="mlp-card mlp-project-card"
            role="button"
            tabIndex={0}
            data-testid={`project-card-${p.id}`}
            onClick={() => onOpen(p.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onOpen(p.id);
              }
            }}
          >
            <div className="mlp-project-name">{p.name}</div>
            {p.description && <div className="mlp-muted">{p.description}</div>}
            <div className="mlp-project-meta mlp-muted">
              K={p.labels_per_unit} · golds {Math.round(p.gold_ratio * 100)}% · template #
              {p.template_id} v{p.template_version}
            </div>
            <div className="mlp-actions" style={{ marginTop: 10 }}>
              <StartLabeling
                client={client}
                projectId={p.id}
                apiKey={apiKey}
                label="Label this →"
                className="mlp-btn"
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
