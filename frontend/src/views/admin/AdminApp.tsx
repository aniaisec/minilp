// Admin shell (§11) — a tiny hash router so the admin surface needs no routing
// dependency, matching the annotation view's zero-dep philosophy. Routes:
//
//   #/admin                     → dashboard (project list)
//   #/admin/new                 → new-project wizard
//   #/admin/templates           → template gallery
//   #/admin/templates/new       → visual builder, from scratch      (M6, §2.5)
//   #/admin/templates/<id>/edit → visual builder, editing           (M6, §2.5)
//   #/admin/project/<id>        → per-project surface, default section
//   #/admin/project/<id>/<tab>  → a named section of it: progress / units /
//                                 bias / roster / judges / active-learning /
//                                 configure / add / export   (UX plan, phase 3)
//
// The project section lives in the URL rather than in component state so it is
// linkable, survives a refresh, and can name the last breadcrumb. Before phase
// 3 a refresh silently returned you to Progress.
//
// The API key is read from ?key= (as the annotation view does) and can also be
// pasted into the header field, so an admin can drive the whole surface with the
// same key that seeds their curl calls.

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { MiniLpClient } from "../../api/client";
import { AdminShell, type Crumb, type NavKey } from "./AdminShell";
import { buildCommands, usePaletteIndex } from "./commands";
import { Dashboard } from "./Dashboard";
import { MarketplacePanel } from "./MarketplacePanel";
import { ProjectView } from "./ProjectView";
import { TemplateGallery } from "./TemplateGallery";
import { Wizard } from "./Wizard";
import { TemplateEditor } from "./builder/TemplateEditor";
import {
  DEFAULT_PROJECT_TAB,
  projectTabHref,
  projectTabLabel,
  resolveProjectTab,
} from "./projectTabs";

function useHash(): string {
  const [hash, setHash] = useState(() => window.location.hash || "#/admin");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/admin");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

function nav(to: string) {
  window.location.hash = to;
}

const KEY_STORAGE = "mlp.apiKey";

// The project's real name, for the `<h1>` and the breadcrumb. The shell renders
// the heading, so the name has to be resolved here rather than inside
// `ProjectView` — "Project #3" told an admin nothing they did not already know
// from the URL. Returns null until it arrives (and if it never does), so the
// caller can fall back to the id rather than render an empty heading.
function useProjectName(client: MiniLpClient, projectId: number | null): string | null {
  const [name, setName] = useState<string | null>(null);
  useEffect(() => {
    setName(null);
    if (projectId === null) return;
    let live = true;
    client
      .getProject(projectId)
      .then((p) => live && setName(p.name))
      .catch(() => {
        /* the id in the title is a fine fallback; the panels report the error */
      });
    return () => {
      live = false;
    };
  }, [client, projectId]);
  return name;
}

// The key may arrive either before the hash (?key=…#/admin, in location.search)
// or inside the hash (#/admin?key=…, which browsers keep in location.hash, not
// search). Accept both so the URLs in the README/Testing docs just work.
function keyFromUrl(hash: string): string {
  const fromSearch = new URLSearchParams(window.location.search).get("key");
  if (fromSearch) return fromSearch;
  const q = hash.indexOf("?");
  if (q >= 0) return new URLSearchParams(hash.slice(q + 1)).get("key") ?? "";
  return "";
}

// Resolve the key at load: an explicit key in the URL wins (and reseeds storage),
// otherwise fall back to the last key we saved. This is what makes a plain refresh
// of #/admin — or clicking a nav link, which drops ?key= from the URL — keep
// working instead of dropping back to "missing API key".
function initialKey(hash: string): string {
  const fromUrl = keyFromUrl(hash);
  if (fromUrl) return fromUrl;
  try {
    return window.localStorage.getItem(KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

export function AdminApp() {
  const hash = useHash();
  const [apiKey, setApiKey] = useState<string>(() => initialKey(hash));
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Persist the key so a refresh auto-loads it. Cleared from storage when emptied.
  useEffect(() => {
    try {
      if (apiKey) window.localStorage.setItem(KEY_STORAGE, apiKey);
      else window.localStorage.removeItem(KEY_STORAGE);
    } catch {
      /* storage unavailable — key stays session-only */
    }
  }, [apiKey]);

  const client = useMemo(() => new MiniLpClient({ apiKey: apiKey || undefined }), [apiKey]);

  // Parse the route from the path portion only (strip any ?query in the hash).
  const path = hash.split("?")[0];
  const parts = path.replace(/^#\/?/, "").split("/"); // e.g. ["admin","project","3","units"]

  // Resolved before the branching below, because hooks cannot live inside it.
  // `Number.isInteger` rather than a bare `Number()`: `#/admin/project/abc`
  // otherwise produced a NaN id and a project screen fetching `/projects/NaN`.
  const maybeId = parts[1] === "project" && parts[2] ? Number(parts[2]) : null;
  const projectId = maybeId !== null && Number.isInteger(maybeId) ? maybeId : null;
  const projectName = useProjectName(client, projectId);

  // The command palette (phase 6). Assembled here rather than in the shell for
  // the same reason the title is: the shell owns chrome, and only the router
  // knows which project you are in — which is what decides whether "Export
  // labels" and the nine section jumps are on offer at all.
  const [paletteUsed, setPaletteUsed] = useState(false);
  const onPaletteOpen = useCallback(() => setPaletteUsed(true), []);
  const paletteIndex = usePaletteIndex(client, paletteUsed);
  const commands = useMemo(
    () =>
      buildCommands({
        client,
        apiKey,
        theme,
        onThemeChange: setTheme,
        projectId,
        projectName,
        index: paletteIndex,
      }),
    [client, apiKey, theme, setTheme, projectId, projectName, paletteIndex],
  );

  // One resolution step producing everything the shell needs: which rail item
  // is current, what the `<h1>` says, and how you got here. Previously the
  // route only produced a body, and the header had no idea where you were —
  // which is exactly why nothing in the chrome could tell you.
  const PROJECTS_CRUMB: Crumb = { label: "Projects", href: "#/admin" };
  const TEMPLATES_CRUMB: Crumb = { label: "Templates", href: "#/admin/templates" };

  let active: NavKey = "projects";
  let title = "Projects";
  let crumbs: Crumb[] = [];
  // Only set where the current page is *not* the `<h1>` — inside a project the
  // heading names the project and the last crumb names the section.
  let currentCrumb: string | undefined;
  let body: ReactNode;

  if (parts[1] === "templates" && parts[2] === "new") {
    active = "templates";
    title = "New template";
    crumbs = [TEMPLATES_CRUMB];
    body = <TemplateEditor client={client} onSaved={() => nav("#/admin/templates")} />;
  } else if (parts[1] === "templates" && parts[2] && parts[3] === "edit") {
    active = "templates";
    title = `Edit template #${parts[2]}`;
    crumbs = [TEMPLATES_CRUMB];
    body = (
      <TemplateEditor
        client={client}
        templateId={Number(parts[2])}
        onSaved={() => nav("#/admin/templates")}
      />
    );
  } else if (parts[1] === "templates") {
    active = "templates";
    title = "Templates";
    body = (
      <TemplateGallery
        client={client}
        onNew={() => nav("#/admin/templates/new")}
        onEdit={(id) => nav(`#/admin/templates/${id}/edit`)}
      />
    );
  } else if (parts[1] === "marketplace") {
    active = "marketplace";
    title = "Marketplace";
    body = <MarketplacePanel client={client} />;
  } else if (parts[1] === "new") {
    active = "new";
    title = "New project";
    crumbs = [PROJECTS_CRUMB];
    // Land on the canonical section URL, not the bare project path: every link
    // the app produces itself names the section, so a copied URL always does.
    body = (
      <Wizard
        client={client}
        onCreated={(id) => nav(projectTabHref(id, DEFAULT_PROJECT_TAB))}
      />
    );
  } else if (projectId !== null) {
    const tab = resolveProjectTab(parts[3]);
    active = "projects";
    title = projectName ?? `Project #${projectId}`;
    crumbs = [
      PROJECTS_CRUMB,
      { label: title, href: projectTabHref(projectId, DEFAULT_PROJECT_TAB) },
    ];
    currentCrumb = projectTabLabel(tab);
    body = <ProjectView client={client} projectId={projectId} apiKey={apiKey} tab={tab} />;
  } else {
    body = (
      <Dashboard
        client={client}
        apiKey={apiKey}
        onOpen={(id) => nav(projectTabHref(id, DEFAULT_PROJECT_TAB))}
        onNew={() => nav("#/admin/new")}
      />
    );
  }

  return (
    <AdminShell
      client={client}
      apiKey={apiKey}
      onApiKeyChange={setApiKey}
      theme={theme}
      onThemeChange={setTheme}
      active={active}
      title={title}
      crumbs={crumbs}
      currentCrumb={currentCrumb}
      commands={commands}
      onPaletteOpen={onPaletteOpen}
    >
      {!apiKey && (
        <div className="mlp-card mlp-muted" style={{ marginBottom: "var(--gap)" }}>
          Add an <strong>admin</strong> API key from the key button in the header (or open
          with <code>?key=&lt;key&gt;</code>) to load projects.
        </div>
      )}
      {body}
    </AdminShell>
  );
}
