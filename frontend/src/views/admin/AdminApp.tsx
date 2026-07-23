// Admin shell (§11) — a tiny hash router so the admin surface needs no routing
// dependency, matching the annotation view's zero-dep philosophy. Routes:
//
//   #/admin                 → dashboard (project list)
//   #/admin/new             → new-project wizard
//   #/admin/project/<id>    → per-project progress / units / bias / roster
//
// The API key is read from ?key= (as the annotation view does) and can also be
// pasted into the header field, so an admin can drive the whole surface with the
// same key that seeds their curl calls.

import { useEffect, useMemo, useState } from "react";

import { MiniLpClient } from "../../api/client";
import { Dashboard } from "./Dashboard";
import { ProjectView } from "./ProjectView";
import { TemplateGallery } from "./TemplateGallery";
import { Wizard } from "./Wizard";

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
  const parts = path.replace(/^#\/?/, "").split("/"); // e.g. ["admin","project","3"]
  let body;
  if (parts[1] === "templates") {
    body = <TemplateGallery client={client} />;
  } else if (parts[1] === "new") {
    body = <Wizard client={client} onCreated={(id) => nav(`#/admin/project/${id}`)} />;
  } else if (parts[1] === "project" && parts[2]) {
    body = (
      <ProjectView
        client={client}
        projectId={Number(parts[2])}
        onBack={() => nav("#/admin")}
      />
    );
  } else {
    body = (
      <Dashboard
        client={client}
        onOpen={(id) => nav(`#/admin/project/${id}`)}
        onNew={() => nav("#/admin/new")}
      />
    );
  }

  return (
    <div className="mlp-app mlp-admin">
      <header className="mlp-admin-bar">
        <div className="mlp-admin-nav">
          <a className="mlp-admin-brand" href="#/admin">
            MiniLP · Admin
          </a>
          <a className="mlp-admin-link" href="#/admin">
            Projects
          </a>
          <a className="mlp-admin-link" href="#/admin/templates">
            Templates
          </a>
          <a className="mlp-admin-link" href="#/admin/new">
            New project
          </a>
        </div>
        <div className="mlp-admin-tools">
          <input
            className="mlp-key-input"
            type="password"
            value={apiKey}
            placeholder="API key"
            onChange={(e) => setApiKey(e.target.value)}
          />
          <button
            className="mlp-btn"
            onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
          >
            {theme === "light" ? "🌙" : "☀️"}
          </button>
        </div>
      </header>
      <main className="mlp-admin-main">
        {!apiKey && (
          <div className="mlp-card mlp-muted" style={{ marginBottom: "var(--gap)" }}>
            Paste an <strong>admin</strong> API key above (or open with{" "}
            <code>?key=&lt;key&gt;</code>) to load projects.
          </div>
        )}
        {body}
      </main>
    </div>
  );
}
