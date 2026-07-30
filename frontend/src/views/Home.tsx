// Annotator home (M8, §11) — the M5 landing page promoted to a real home screen.
//
// Three things make it a *home* rather than a start screen:
//
// 1. **A stable route.** `?annotator=&key=` with no `project=` is somewhere you
//    can return to, and every project screen carries a control that returns you
//    here (see `ExitToHome`).
// 2. **Two presentations of one list.** A dense table and a card grid, toggled
//    and remembered like the theme and auto-submit preferences. Both render from
//    the *same* fetch — which is why the counts on a card can never disagree
//    with the counts on a row (§12 M8 acceptance).
// 3. **An empty state that says which emptiness it is.** "No projects exist yet"
//    and "you have labeled everything available" are different situations for
//    the person reading them, and a single "nothing here" would hide that.

import { useCallback, useEffect, useMemo, useState } from "react";

import type { MiniLpClient } from "../api/client";
import type { AvailableProject } from "../api/types";

export const HOME_VIEW_KEY = "mlp.homeView";

export type HomeView = "table" | "cards";

export function readHomeView(fallback: HomeView = "table"): HomeView {
  try {
    const stored = window.localStorage.getItem(HOME_VIEW_KEY);
    return stored === "cards" || stored === "table" ? stored : fallback;
  } catch {
    return fallback;
  }
}

/** Build the URL of a project screen from home. Exported so the exit control and
 *  the tests agree on the shape of the link rather than each inventing one. */
export function projectUrl(projectId: number, annotator: number, key: string): string {
  const q = new URLSearchParams({ project: String(projectId), annotator: String(annotator) });
  if (key) q.set("key", key);
  return `?${q.toString()}`;
}

export function homeUrl(annotator: number, key: string): string {
  const q = new URLSearchParams({ annotator: String(annotator) });
  if (key) q.set("key", key);
  return `?${q.toString()}`;
}

function openProject(projectId: number, annotator: number, key: string) {
  // Full navigation (not just hash) so AnnotatePage re-reads its config cleanly.
  window.location.search = projectUrl(projectId, annotator, key);
}

/** How far through its work a project is — the card's fill bar. */
function fillPercent(p: AvailableProject): number {
  const done = p.your_labels;
  const total = done + p.available_labels;
  if (total <= 0) return 100;
  return Math.round((done / total) * 100);
}

function blockedOrDone(p: AvailableProject): string | null {
  if (p.blocked_reason) return p.blocked_reason;
  if (p.available_labels === 0) {
    return p.your_labels > 0 ? "You have labeled everything here." : "No work left in this project.";
  }
  return null;
}

export interface HomeProps {
  client: MiniLpClient;
  annotator: number;
  apiKey: string;
  /** Seeds the very first render and the tests; the stored preference wins after. */
  initialView?: HomeView;
}

export function Home({ client, annotator, apiKey, initialView = "table" }: HomeProps) {
  const [projects, setProjects] = useState<AvailableProject[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<HomeView>(() => readHomeView(initialView));

  const load = useCallback(() => {
    setError(null);
    client
      .availableWork(annotator)
      .then((w) => setProjects(w.projects))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [client, annotator]);

  useEffect(load, [load]);

  const setAndRemember = useCallback((next: HomeView) => {
    setView(next);
    try {
      window.localStorage.setItem(HOME_VIEW_KEY, next);
    } catch {
      /* storage unavailable — keep it session-only */
    }
  }, []);

  const totals = useMemo(() => {
    const list = projects ?? [];
    return {
      labels: list.reduce((a, p) => a + p.available_labels, 0),
      mine: list.reduce((a, p) => a + p.your_labels, 0),
      workable: list.filter((p) => p.eligible && p.available_labels > 0).length,
    };
  }, [projects]);

  const empty = projects !== null && projects.length === 0;
  // "Nothing exists yet" and "you finished everything" are different messages.
  const drained = projects !== null && projects.length > 0 && totals.workable === 0;

  return (
    <div className="mlp-annotate" style={{ maxWidth: "var(--content-lg)", margin: "0 auto" }}>
      <div className="mlp-landing-head">
        <div>
          <h2 style={{ margin: 0 }}>Your tasks</h2>
          <span className="mlp-muted" data-testid="home-summary">
            annotator #{annotator} · {totals.labels} label{totals.labels === 1 ? "" : "s"} available
            {totals.mine > 0 ? ` · ${totals.mine} submitted by you` : ""}
          </span>
        </div>
        <div className="mlp-view-toggle" role="group" aria-label="View">
          <button
            type="button"
            className={`mlp-btn ${view === "table" ? "mlp-btn-primary" : ""}`}
            aria-pressed={view === "table"}
            onClick={() => setAndRemember("table")}
            data-testid="view-table"
          >
            Table
          </button>
          <button
            type="button"
            className={`mlp-btn ${view === "cards" ? "mlp-btn-primary" : ""}`}
            aria-pressed={view === "cards"}
            onClick={() => setAndRemember("cards")}
            data-testid="view-cards"
          >
            Cards
          </button>
        </div>
      </div>

      {error && (
        <div className="mlp-card" style={{ borderColor: "var(--danger)" }} data-testid="home-error">
          {error}
        </div>
      )}
      {!projects && !error && <div className="mlp-card">Loading tasks…</div>}

      {empty && (
        <div className="mlp-card mlp-muted" data-testid="home-empty">
          <strong>No projects yet.</strong>
          <p style={{ margin: "6px 0 0" }}>
            Nothing has been set up for labeling. An admin creates projects from the admin
            surface — once one exists it will appear here.
          </p>
        </div>
      )}

      {drained && (
        <div className="mlp-card mlp-muted" data-testid="home-drained">
          <strong>All caught up.</strong>
          <p style={{ margin: "6px 0 0" }}>
            {totals.mine > 0
              ? `You have labeled everything available to you (${totals.mine} so far). New work will show up here.`
              : "There is no work available to you right now."}
          </p>
        </div>
      )}

      {projects && projects.length > 0 && view === "table" && (
        <HomeTable projects={projects} annotator={annotator} apiKey={apiKey} />
      )}
      {projects && projects.length > 0 && view === "cards" && (
        <HomeCards projects={projects} annotator={annotator} apiKey={apiKey} />
      )}
    </div>
  );
}

function HomeTable({
  projects,
  annotator,
  apiKey,
}: {
  projects: AvailableProject[];
  annotator: number;
  apiKey: string;
}) {
  return (
    <table className="mlp-table mlp-card" data-testid="home-table">
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
          const note = blockedOrDone(p);
          return (
            <tr
              key={p.project_id}
              data-testid={`home-row-${p.project_id}`}
              className={disabled ? "" : "mlp-landing-row"}
              onClick={() => !disabled && openProject(p.project_id, annotator, apiKey)}
            >
              <td>
                <div className="mlp-landing-name">{p.name}</div>
                {p.blocked_reason && (
                  <div className="mlp-error-text" style={{ fontSize: 12 }}>
                    {p.blocked_reason}
                  </div>
                )}
                {!p.blocked_reason && note && (
                  <div className="mlp-muted" style={{ fontSize: 12 }}>
                    {note}
                  </div>
                )}
                {!note && p.description && (
                  <div className="mlp-muted" style={{ fontSize: 12 }}>
                    {p.description}
                  </div>
                )}
              </td>
              <td data-testid={`home-row-${p.project_id}-available`}>
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
  );
}

function HomeCards({
  projects,
  annotator,
  apiKey,
}: {
  projects: AvailableProject[];
  annotator: number;
  apiKey: string;
}) {
  return (
    <div className="mlp-card-grid" data-testid="home-cards">
      {projects.map((p) => {
        const disabled = !p.eligible || p.available_labels === 0;
        const note = blockedOrDone(p);
        const percent = fillPercent(p);
        return (
          <div
            key={p.project_id}
            className={`mlp-card mlp-project-card${disabled ? " mlp-project-card-off" : ""}`}
            data-testid={`home-card-${p.project_id}`}
          >
            <div className="mlp-project-card-head">
              <div className="mlp-landing-name">{p.name}</div>
              {p.description && !note && (
                <div className="mlp-muted" style={{ fontSize: 12 }}>
                  {p.description}
                </div>
              )}
              {note && (
                <div
                  className={p.blocked_reason ? "mlp-error-text" : "mlp-muted"}
                  style={{ fontSize: 12 }}
                  data-testid={`home-card-${p.project_id}-note`}
                >
                  {note}
                </div>
              )}
            </div>

            <div className="mlp-project-card-stats">
              <div>
                <div className="mlp-stat-value" data-testid={`home-card-${p.project_id}-available`}>
                  {p.available_labels}
                </div>
                <div className="mlp-stat-label">labels available</div>
              </div>
              <div>
                <div className="mlp-stat-value">{p.open_units}</div>
                <div className="mlp-stat-label">units open</div>
              </div>
              <div>
                <div className="mlp-stat-value">{p.your_labels}</div>
                <div className="mlp-stat-label">your labels</div>
              </div>
            </div>

            <div
              className="mlp-fill"
              role="progressbar"
              aria-label={`${p.name} progress`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={percent}
            >
              <span style={{ width: `${percent}%` }} />
            </div>

            <button
              className="mlp-btn mlp-btn-primary mlp-project-card-cta"
              disabled={disabled}
              onClick={() => openProject(p.project_id, annotator, apiKey)}
            >
              {p.available_labels === 0 ? "Done" : "Label"}
            </button>
          </div>
        );
      })}
    </div>
  );
}
