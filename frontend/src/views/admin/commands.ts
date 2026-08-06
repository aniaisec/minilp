// What the command palette can do (UX plan, phase 6).
//
// Split from the widget on the same line as the rest of the admin surface: the
// palette knows how to run a list of commands, `AdminApp` knows what the list
// is. That is also what keeps this file testable — `buildCommands` is a pure
// function of the route and the fetched index, so "does Cmd+K offer Export when
// you are inside a project" is a unit test rather than a click-through.
//
// The command set is the plan's: every project, every template, every admin
// destination, and the actions that otherwise take three clicks (new project,
// start labeling, toggle theme, export). Plus the *current* project's nine
// sections, which is where the palette earns its keep — the sections are two
// navigation levels down and there is no other way to reach one directly.

import { useEffect, useState } from "react";

import type { MiniLpClient } from "../../api/client";
import type { ProjectSummary, Template } from "../../api/types";
import type { Command } from "../../components/CommandPalette";
import { labelingUrl } from "./StartLabeling";
import {
  DEFAULT_PROJECT_TAB,
  PROJECT_TAB_GROUPS,
  projectTabHref,
  type ProjectTab,
} from "./projectTabs";

/** The two lists that cannot be known from the route alone. */
export interface PaletteIndex {
  projects: ProjectSummary[];
  templates: Template[];
}

export const EMPTY_INDEX: PaletteIndex = { projects: [], templates: [] };

export interface CommandContext {
  client: MiniLpClient;
  apiKey: string;
  theme: "light" | "dark";
  onThemeChange: (theme: "light" | "dark") => void;
  /** The project currently open, or null outside one. Scopes the sections
   *  group and the two project-shaped actions. */
  projectId: number | null;
  /** Resolved name of that project, for labels that say which one. */
  projectName?: string | null;
  index: PaletteIndex;
  /** Injectable so tests can assert the destination without a jsdom navigation,
   *  which is unimplemented and logs an error. */
  navigate?: (href: string) => void;
}

/** A hash destination stays inside the SPA; anything else is a real page load
 *  (the review queue and the annotation view are outside the admin router). */
function defaultNavigate(href: string): void {
  if (href.startsWith("#")) window.location.hash = href;
  else window.location.href = href;
}

const GROUP_GO = "Go to";
const GROUP_SECTIONS = "This project";
const GROUP_PROJECTS = "Projects";
const GROUP_TEMPLATES = "Templates";
const GROUP_ACTIONS = "Actions";

/** Synonyms per section — what an admin types when they do not remember what
 *  we decided to call it. The section's own slug is added to these
 *  automatically, because label and slug diverge in three places ("Annotators"
 *  is `roster`, "Configure" is `config`, "Add tasks" is `add`) and the slug is
 *  what the README, the runbook and every URL in Testing.txt actually say. */
const SECTION_KEYWORDS: Partial<Record<ProjectTab, string>> = {
  progress: "funnel batches status",
  units: "browser rows tasks",
  bias: "distribution variant balance",
  roster: "people reputation annotator",
  judges: "models llm enroll",
  "active-learning": "informativeness ranking checkpoint",
  config: "settings template edit",
  add: "upload import jsonl bulk tasks",
  export: "download csv jsonl parquet labels",
};

export function buildCommands(ctx: CommandContext): Command[] {
  const { apiKey, client, index, projectId, projectName, theme, onThemeChange } = ctx;
  const go = ctx.navigate ?? defaultNavigate;
  const commands: Command[] = [];

  // ---- destinations --------------------------------------------------------
  commands.push(
    {
      id: "go:projects",
      group: GROUP_GO,
      label: "Projects",
      hint: "Dashboard",
      keywords: "home dashboard list",
      run: () => go("#/admin"),
    },
    {
      id: "go:templates",
      group: GROUP_GO,
      label: "Templates",
      hint: "Gallery",
      keywords: "gallery schema",
      run: () => go("#/admin/templates"),
    },
    {
      id: "go:marketplace",
      group: GROUP_GO,
      label: "Marketplace",
      hint: "Import and export bundles",
      keywords: "bundle share import",
      run: () => go("#/admin/marketplace"),
    },
  );
  if (apiKey) {
    // Outside the admin router, and it needs the key on the URL — the same link
    // the rail builds, for the same reason: no re-auth.
    commands.push({
      id: "go:review",
      group: GROUP_GO,
      label: "Review queue",
      hint: "Escalated units",
      keywords: "escalation adjudicate",
      run: () =>
        go(`${window.location.pathname}?review=1&key=${encodeURIComponent(apiKey)}`),
    });
  }

  // ---- the current project's sections ---------------------------------------
  //
  // Only offered inside a project. Outside one there is no answer to "units of
  // what", and an entry that silently picks a project for you is worse than no
  // entry at all.
  if (projectId !== null) {
    const where = projectName ?? `Project #${projectId}`;
    for (const group of PROJECT_TAB_GROUPS) {
      for (const tab of group.items) {
        commands.push({
          id: `section:${tab.id}`,
          group: GROUP_SECTIONS,
          label: tab.label,
          hint: `${where} · ${group.heading}`,
          keywords: `${tab.id} ${SECTION_KEYWORDS[tab.id] ?? ""}`.trim(),
          run: () => go(projectTabHref(projectId, tab.id)),
        });
      }
    }
  }

  // ---- every project and every template -------------------------------------
  for (const project of index.projects) {
    commands.push({
      id: `project:${project.id}`,
      group: GROUP_PROJECTS,
      label: project.name,
      hint: project.description ?? `Project #${project.id}`,
      keywords: `project #${project.id}`,
      run: () => go(projectTabHref(project.id, DEFAULT_PROJECT_TAB)),
    });
  }
  for (const template of index.templates) {
    commands.push({
      id: `template:${template.id}`,
      group: GROUP_TEMPLATES,
      label: template.name,
      hint: `${template.kind} · v${template.version}`,
      keywords: `template #${template.id} edit builder`,
      run: () => go(`#/admin/templates/${template.id}/edit`),
    });
  }

  // ---- actions --------------------------------------------------------------
  commands.push(
    {
      id: "action:new-project",
      group: GROUP_ACTIONS,
      label: "New project",
      hint: "Wizard",
      keywords: "create add",
      run: () => go("#/admin/new"),
    },
    {
      id: "action:new-template",
      group: GROUP_ACTIONS,
      label: "New template",
      hint: "Visual builder",
      keywords: "create add schema",
      run: () => go("#/admin/templates/new"),
    },
  );

  if (projectId !== null) {
    commands.push({
      id: "action:export",
      group: GROUP_ACTIONS,
      label: "Export labels",
      hint: projectName ?? `Project #${projectId}`,
      keywords: "download csv jsonl parquet",
      run: () => go(projectTabHref(projectId, "export")),
    });
  }

  if (apiKey) {
    commands.push({
      id: "action:start-labeling",
      group: GROUP_ACTIONS,
      label: projectId === null ? "Start labeling" : "Start labeling this project",
      hint: "Open the annotation view as yourself",
      keywords: "annotate label task",
      // An admin holds a *user* token and the annotation view wants an
      // *annotator* id; `POST /me:annotator` bridges them (see StartLabeling).
      // Failure is deliberately silent: the palette has already closed, and the
      // fallback — the rail's own button, which reports errors properly — is
      // one keystroke away.
      run: () => {
        void client
          .myAnnotator()
          .then((me) => go(labelingUrl(me.id, apiKey, projectId ?? undefined)))
          .catch(() => {});
      },
    });
  }

  commands.push({
    id: "action:theme",
    group: GROUP_ACTIONS,
    // Named for what the press does, not for what the theme currently is — the
    // same rule the rail's collapse toggle follows.
    label: theme === "light" ? "Switch to dark theme" : "Switch to light theme",
    hint: "Appearance",
    keywords: "theme dark light mode appearance contrast",
    run: () => onThemeChange(theme === "light" ? "dark" : "light"),
  });

  return commands;
}

/**
 * The half of the command set that has to be fetched.
 *
 * `enabled` is false until the palette is opened for the first time. Two list
 * requests on every admin page load, for a feature most sessions never invoke,
 * is a cost with no return; deferring them to first open costs one render of a
 * palette whose static commands are already there.
 *
 * Both failures are swallowed. A palette that offers destinations and actions
 * while the project list is still loading — or has failed — is useful; one that
 * refuses to open because a list request 401'd is not.
 */
export function usePaletteIndex(client: MiniLpClient, enabled: boolean): PaletteIndex {
  const [index, setIndex] = useState<PaletteIndex>(EMPTY_INDEX);

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    void Promise.all([
      client.listProjects().catch((): ProjectSummary[] => []),
      client.listTemplates().catch((): Template[] => []),
    ]).then(([projects, templates]) => {
      if (live) setIndex({ projects, templates });
    });
    return () => {
      live = false;
    };
    // `client` is rebuilt when the API key changes, which is exactly when the
    // index needs refetching — the previous key may have seen nothing.
  }, [client, enabled]);

  return index;
}
