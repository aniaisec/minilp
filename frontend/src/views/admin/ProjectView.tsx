// Per-project admin surface (§11), rebuilt for phase 3 of the UX plan.
//
// What changed and why: the nine destinations used to be a single horizontal
// strip of `<button>` tabs held in component state. At 14px they overflowed on
// a laptop, they gave no sense of grouping, and — because the tab was state and
// not a route — a refresh silently dropped you back on Progress and there was
// no way to send someone a link to the unit browser.
//
// They are now a grouped secondary rail of *links*, one route each
// (`#/admin/project/3/units`). Links rather than an ARIA tablist because that
// is what they are: each one changes the URL, so `aria-current="page"` is the
// honest marking and the browser's own back button does the right thing.
//
// The header carries the project's state and completion, which previously
// existed only once you were already inside the Progress tab.

import { useEffect, useId, useState } from "react";

import type { MiniLpClient } from "../../api/client";
import type { Progress } from "../../api/types";
import { ActiveLearningPanel } from "./ActiveLearningPanel";
import { AddTasksPanel } from "./AddTasksPanel";
import { BiasPanel } from "./BiasPanel";
import { ConfigPanel } from "./ConfigPanel";
import { ExportPanel } from "./ExportPanel";
import { JudgesPanel } from "./JudgesPanel";
import { ProgressPanel } from "./ProgressPanel";
import { RosterPanel } from "./RosterPanel";
import { StartLabeling } from "./StartLabeling";
import { UnitBrowser } from "./UnitBrowser";
import { WebhooksPanel } from "./WebhooksPanel";
import { pct } from "./format";
import {
  PROJECT_TAB_GROUPS,
  projectCompletion,
  projectState,
  projectTabHref,
  projectTabLabel,
  type ProjectTab,
} from "./projectTabs";
import { Bar, Pill } from "./widgets";

// Most sections read better in a column. "Configure" holds the template
// builder, which wants the room — capping it there would squeeze the live
// preview back out of view, which is the whole thing the side-by-side layout
// fixes.
const WIDE_TABS = new Set<ProjectTab>(["config"]);

export function ProjectView({
  client,
  projectId,
  apiKey,
  tab,
}: {
  client: MiniLpClient;
  projectId: number;
  /** Carried into the annotation-view URL so "Start labeling" needs no re-auth. */
  apiKey: string;
  /** Resolved from the URL by `AdminApp`; this component holds no tab state. */
  tab: ProjectTab;
}) {
  // Progress is fetched here rather than inside `ProgressPanel` because the
  // header needs the funnel on *every* section, not just on Progress. The panel
  // takes it as a prop, so this is one request per project rather than two on
  // the Progress route.
  const [progress, setProgress] = useState<Progress | null>(null);
  const [progressError, setProgressError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setProgress(null);
    setProgressError(null);
    client
      .getProgress(projectId)
      .then((p) => live && setProgress(p))
      .catch((e) => live && setProgressError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [client, projectId]);

  const navId = useId();
  const panelHeadingId = `${navId}-panel`;
  const funnel = progress?.funnel;

  return (
    <div className="mlp-project">
      <div className="mlp-project-head">
        <div className="mlp-project-status" data-testid="project-status">
          {funnel ? (
            <>
              <Pill tone={projectState(funnel).tone}>{projectState(funnel).label}</Pill>
              {funnel.escalated > 0 && <Pill tone="warn">{funnel.escalated} escalated</Pill>}
              <span className="mlp-muted">
                {funnel.finalized} of {funnel.total} units finalized (
                {pct(projectCompletion(funnel))})
              </span>
            </>
          ) : progressError ? (
            // Not a blocker: the sections below still work without the header
            // summary, so this states what is missing rather than replacing the
            // whole screen with an error.
            <span className="mlp-muted mlp-project-head-error">
              Project summary unavailable — {progressError}
            </span>
          ) : (
            <span className="mlp-muted" role="status">
              Loading project summary…
            </span>
          )}

          <div className="mlp-project-actions">
            {/* Exit to home (M8, §11): every project screen carries a visible
                way back to the annotator home, this one included. It resolves
                the admin's own rater record on click, the same bridge "Start
                labeling" uses — an admin who has never labeled still has
                somewhere to land. */}
            <StartLabeling
              client={client}
              apiKey={apiKey}
              label="← Home"
              className="mlp-btn mlp-btn-exit"
            />
            <StartLabeling client={client} projectId={projectId} apiKey={apiKey} />
          </div>
        </div>

        {funnel && (
          <Bar
            frac={projectCompletion(funnel)}
            color="var(--ok)"
            label={<span className="mlp-visually-hidden">Project completion</span>}
          />
        )}
      </div>

      <div className="mlp-project-body">
        <div className="mlp-subnav">
          {PROJECT_TAB_GROUPS.map((group) => {
            const headingId = `${navId}-${group.heading.toLowerCase()}`;
            return (
              // A real `<nav>` per group, named by its own heading, rather than
              // four styled divs: the grouping is the point, and a grouping that
              // exists only in the pixels is not available to everyone.
              <nav key={group.heading} aria-labelledby={headingId} className="mlp-subnav-group">
                <h2 className="mlp-subnav-heading" id={headingId}>
                  {group.heading}
                </h2>
                <ul>
                  {group.items.map((item) => (
                    <li key={item.id}>
                      <a
                        className="mlp-subnav-item"
                        href={projectTabHref(projectId, item.id)}
                        data-testid={`tab-${item.id}`}
                        aria-current={item.id === tab ? "page" : undefined}
                      >
                        {item.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </nav>
            );
          })}
        </div>

        {/* The panel is a named region so the heading outline descends without
            skipping: `<h1>` (project, in the command bar) → this `<h2>` → the
            `<h3>`s the panels already use. The name duplicates the current
            sub-nav link, so it is hidden visually and kept for screen readers. */}
        <section
          className="mlp-project-panel"
          aria-labelledby={panelHeadingId}
          style={{ maxWidth: WIDE_TABS.has(tab) ? "none" : "var(--content-xl)" }}
        >
          <h2 className="mlp-visually-hidden" id={panelHeadingId}>
            {projectTabLabel(tab)}
          </h2>

          {tab === "progress" &&
            (progressError ? (
              <div className="mlp-card mlp-error">{progressError}</div>
            ) : progress ? (
              <ProgressPanel data={progress} />
            ) : (
              <div className="mlp-card" role="status">
                Loading progress…
              </div>
            ))}
          {tab === "units" && <UnitBrowser client={client} projectId={projectId} />}
          {tab === "bias" && <BiasPanel client={client} projectId={projectId} />}
          {tab === "roster" && <RosterPanel client={client} projectId={projectId} />}
          {tab === "judges" && (
            <>
              <JudgesPanel client={client} projectId={projectId} />
              <WebhooksPanel client={client} projectId={projectId} />
            </>
          )}
          {tab === "active-learning" && (
            <ActiveLearningPanel client={client} projectId={projectId} />
          )}
          {tab === "config" && <ConfigPanel client={client} projectId={projectId} />}
          {tab === "add" && <AddTasksPanel client={client} projectId={projectId} />}
          {tab === "export" && <ExportPanel client={client} projectId={projectId} />}
        </section>
      </div>
    </div>
  );
}
