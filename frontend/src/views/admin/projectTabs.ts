// The project-view section model (UX plan, phase 3).
//
// Split out of `ProjectView` so the router can resolve a tab slug — and label a
// breadcrumb with it — without importing every panel in the project surface.
//
// Nine flat horizontal tabs at 14px overflowed on a laptop and gave no sense of
// grouping. The grouping below is not cosmetic: it separates read-only
// inspection (Monitor) from the people who produce the data (People), from the
// machinery that runs unattended (Automate), from the actions that change
// project state (Manage). An admin who wants to look at something and an admin
// who wants to change something now start in different places.

import type { Progress } from "../../api/types";

export type ProjectTab =
  | "progress"
  | "units"
  | "bias"
  | "roster"
  | "judges"
  | "active-learning"
  | "config"
  | "add"
  | "export";

export interface ProjectTabDef {
  id: ProjectTab;
  label: string;
}

export interface ProjectTabGroup {
  /** The quiet section heading, and the accessible name of the group's `<nav>`. */
  heading: string;
  items: ProjectTabDef[];
}

export const PROJECT_TAB_GROUPS: ProjectTabGroup[] = [
  {
    heading: "Monitor",
    items: [
      { id: "progress", label: "Progress" },
      { id: "units", label: "Units" },
      { id: "bias", label: "Bias & distribution" },
    ],
  },
  {
    heading: "People",
    items: [
      { id: "roster", label: "Annotators" },
      { id: "judges", label: "Judges" },
    ],
  },
  {
    heading: "Automate",
    items: [{ id: "active-learning", label: "Active learning" }],
  },
  {
    heading: "Manage",
    items: [
      { id: "config", label: "Configure" },
      { id: "add", label: "Add tasks" },
      { id: "export", label: "Export" },
    ],
  },
];

export const PROJECT_TABS: ProjectTabDef[] = PROJECT_TAB_GROUPS.flatMap((g) => g.items);

export const DEFAULT_PROJECT_TAB: ProjectTab = "progress";

const BY_ID = new Map(PROJECT_TABS.map((t) => [t.id, t]));

/** A tab slug straight off the URL. Anything unrecognised — a typo, a link from
 *  an older build, a truncated paste — lands on Progress rather than on a blank
 *  screen, which is the only sensible thing a router can do with a bad segment. */
export function resolveProjectTab(slug: string | undefined): ProjectTab {
  return slug && BY_ID.has(slug as ProjectTab) ? (slug as ProjectTab) : DEFAULT_PROJECT_TAB;
}

export function projectTabLabel(tab: ProjectTab): string {
  return BY_ID.get(tab)?.label ?? tab;
}

export function projectTabHref(projectId: number, tab: ProjectTab): string {
  return `#/admin/project/${projectId}/${tab}`;
}

// ---- derived project state -------------------------------------------------

export interface ProjectState {
  label: string;
  tone?: "ok" | "warn" | "muted";
}

/** The state pill on the project header.
 *
 *  Derived from the progress funnel rather than stored on the project: there is
 *  no status column on `projects`, and inventing one would mean an admin has to
 *  remember to move a project to "complete" — a field that is wrong the moment
 *  anyone forgets. The funnel already knows, and it cannot go stale. */
export function projectState(funnel: Progress["funnel"]): ProjectState {
  if (funnel.total === 0) return { label: "No tasks", tone: "muted" };
  if (funnel.finalized >= funnel.total) return { label: "Complete", tone: "ok" };
  const started = funnel.in_progress + funnel.labeled + funnel.finalized;
  if (started === 0) return { label: "Not started", tone: "muted" };
  return { label: "In progress" };
}

/** Fraction of units finalized, 0..1. Zero units is 0, not NaN. */
export function projectCompletion(funnel: Progress["funnel"]): number {
  return funnel.total ? funnel.finalized / funnel.total : 0;
}
