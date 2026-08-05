// Admin dashboard (§11): the project list, entry point to the wizard and to each
// project's progress/analytics.

import { useEffect, useState } from "react";

import { Button, Card, EmptyState, ErrorState } from "../../components/ui";
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
      {/* No heading here: the command bar's `<h1>` already names this screen,
          and a second "Projects" directly beneath it is noise in the heading
          outline as well as on the page. */}
      <div className="mlp-actions" style={{ justifyContent: "flex-end" }}>
        <Button variant="primary" onClick={onNew}>
          + New project
        </Button>
      </div>
      {error && (
        <Card>
          <ErrorState title="Could not load your projects" data-testid="dashboard-error">
            {error}
          </ErrorState>
        </Card>
      )}
      {!projects && !error && (
        <Card>
          <p className="mlp-muted" role="status">
            Loading projects…
          </p>
        </Card>
      )}
      {projects && projects.length === 0 && (
        <Card>
          <EmptyState
            title="No projects yet"
            data-testid="dashboard-empty"
            action={
              <Button variant="primary" onClick={onNew}>
                + New project
              </Button>
            }
          >
            A project pairs a template with a pool of units and the rules for labeling them.
            Create one to get started.
          </EmptyState>
        </Card>
      )}
      <div className="mlp-project-grid">
        {projects?.map((p) => (
          // Not `role="button" tabIndex={0}`, which is what this used to be. A
          // clickable div announces as a button whose accessible name is the
          // whole card — every stat, every meta string — and it contains a real
          // button, which is a nesting a screen reader cannot describe.
          //
          // Instead: the *title* is the link. It carries the accessible name
          // and the tab stop, so the card announces as "Preference run, link".
          // The card keeps its click handler purely as a mouse convenience, so
          // the large target still works for people using a pointer.
          <div
            key={p.id}
            className="mlp-card mlp-project-card"
            data-testid={`project-card-${p.id}`}
            onClick={() => onOpen(p.id)}
          >
            <a
              className="mlp-project-name mlp-card-link"
              href={`#/admin/project/${p.id}`}
              onClick={(e) => {
                // The hash router would handle this on its own, but going
                // through `onOpen` keeps one navigation path for both surfaces
                // and lets the caller stay in control (it is injected in tests).
                e.preventDefault();
                e.stopPropagation();
                onOpen(p.id);
              }}
            >
              {p.name}
            </a>
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
