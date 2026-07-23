// Annotator landing page (§11, M5). Shown when an annotator opens the app with a
// key but no project (?annotator=&key=). Lists every project as a row with the
// number of labels still needed; projects that need work sort to the top, most
// first. Clicking a row jumps into the annotation loop for that project by adding
// ?project= to the URL — the same config channel AnnotatePage already reads.

import { useEffect, useState } from "react";

import type { MiniLpClient } from "../api/client";
import type { AvailableProject } from "../api/types";

function openProject(projectId: number, annotator: number, key: string) {
  const q = new URLSearchParams({
    project: String(projectId),
    annotator: String(annotator),
  });
  if (key) q.set("key", key);
  // Full navigation (not just hash) so AnnotatePage re-reads its config cleanly.
  window.location.search = `?${q.toString()}`;
}

export function TasksLanding({
  client,
  annotator,
  apiKey,
}: {
  client: MiniLpClient;
  annotator: number;
  apiKey: string;
}) {
  const [projects, setProjects] = useState<AvailableProject[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    client
      .availableWork(annotator)
      .then((w) => setProjects(w.projects))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [client, annotator]);

  const totalOpen = projects?.reduce((a, p) => a + p.available_labels, 0) ?? 0;

  return (
    <div className="mlp-annotate" style={{ maxWidth: "var(--content-lg)", margin: "0 auto" }}>
      <div className="mlp-landing-head">
        <h2 style={{ margin: 0 }}>Available tasks</h2>
        <span className="mlp-muted">
          annotator #{annotator} · {totalOpen} label{totalOpen === 1 ? "" : "s"} available
        </span>
      </div>

      {error && <div className="mlp-card mlp-error">{error}</div>}
      {!projects && !error && <div className="mlp-card">Loading tasks…</div>}
      {projects && projects.length === 0 && (
        <div className="mlp-card mlp-muted">No projects exist yet.</div>
      )}

      {projects && projects.length > 0 && (
        <table className="mlp-table mlp-card">
          <thead>
            <tr>
              <th>Task</th>
              <th>Labels needed</th>
              <th>Units open</th>
              <th>Your labels</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => {
              const disabled = !p.eligible || p.available_labels === 0;
              return (
                <tr
                  key={p.project_id}
                  className={disabled ? "" : "mlp-landing-row"}
                  onClick={() =>
                    !disabled && openProject(p.project_id, annotator, apiKey)
                  }
                >
                  <td>
                    <div className="mlp-landing-name">{p.name}</div>
                    {p.blocked_reason && (
                      <div className="mlp-error-text" style={{ fontSize: 12 }}>
                        {p.blocked_reason}
                      </div>
                    )}
                    {!p.blocked_reason && p.description && (
                      <div className="mlp-muted" style={{ fontSize: 12 }}>
                        {p.description}
                      </div>
                    )}
                  </td>
                  <td>
                    <strong>{p.available_labels}</strong>
                  </td>
                  <td>{p.open_units}</td>
                  <td>{p.your_labels}</td>
                  <td>
                    <button
                      className="mlp-btn mlp-btn-primary"
                      disabled={disabled}
                      onClick={(e) => {
                        e.stopPropagation();
                        openProject(p.project_id, annotator, apiKey);
                      }}
                    >
                      {p.available_labels === 0 ? "Done" : "Label"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
