// Marketplace (§12, M10): browse the bundles shipped with this instance, import
// one with a click, paste/upload a bundle from somewhere else, and download a
// bundle for anything you already have — a template, a judge config, or (from
// each project's Export tab) a whole project starter kit.
//
// "No hosted registry in v1" (PLAN.md §12) is the whole shape of this panel: the
// left side reads a directory that ships with the repo, the right side is a
// generic import/export surface that works with any bundle from anywhere.

import { useCallback, useEffect, useRef, useState } from "react";

import type { MiniLpClient } from "../../api/client";
import type {
  JudgeConfig,
  LocalBundleInfo,
  MarketplaceBundle,
  MarketplaceImportResult,
  Template,
} from "../../api/types";
import { Pill } from "./widgets";

function download(filename: string, data: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function resultSummary(result: MarketplaceImportResult): string {
  const parts: string[] = [];
  if (result.template) parts.push(`template "${result.template.name}" (#${result.template.id})`);
  if (result.judge_config) {
    parts.push(`judge config "${result.judge_config.name}" v${result.judge_config.prompt_version}`);
  }
  if (result.judge_configs?.length) {
    parts.push(`${result.judge_configs.length} judge config(s)`);
  }
  if (result.project) parts.push(`project "${result.project.name}" (#${result.project.id})`);
  return parts.join(" + ") || "nothing";
}

export function MarketplacePanel({ client }: { client: MiniLpClient }) {
  const [localBundles, setLocalBundles] = useState<LocalBundleInfo[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [judges, setJudges] = useState<JudgeConfig[]>([]);
  const [pasted, setPasted] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [createProject, setCreateProject] = useState(true);
  const [result, setResult] = useState<MarketplaceImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [b, t, j] = await Promise.all([
        client.listLocalBundles(),
        client.listTemplates(),
        client.listJudges().catch(() => [] as JudgeConfig[]),
      ]);
      setLocalBundles(b.bundles);
      setTemplates(t);
      setJudges(j);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (key: string, fn: () => Promise<MarketplaceImportResult>) => {
    setBusy(key);
    setError(null);
    setResult(null);
    try {
      const r = await fn();
      setResult(r);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const importPasted = () => {
    let bundle: MarketplaceBundle;
    try {
      bundle = JSON.parse(pasted);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : "invalid JSON");
      return;
    }
    setParseError(null);
    void act("paste", () => client.importBundle(bundle, createProject));
  };

  const onFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      setPasted(String(reader.result ?? ""));
      setParseError(null);
    };
    reader.readAsText(file);
  };

  return (
    <div className="mlp-stack-lg" data-testid="marketplace-panel">
      <section className="mlp-card">
        <h3 style={{ marginTop: 0 }}>Marketplace (§12)</h3>
        <p className="mlp-muted">
          Export a template, judge config, or project as a shareable JSON bundle; import re-runs
          the exact validation a hand-authored one goes through, so an imported bundle validates
          and previews identically. A judge-config bundle never carries a credential — only the{" "}
          <em>name</em> of an environment variable the server reads at call time.
        </p>

        {error && (
          <div className="mlp-error-text" data-testid="marketplace-error">
            {error}
          </div>
        )}

        {result && (
          <div className="mlp-muted" data-testid="marketplace-result" style={{ marginTop: 6 }}>
            Imported: {resultSummary(result)}.
          </div>
        )}
      </section>

      {/* --- shipped bundles --- */}
      <section className="mlp-card">
        <h3 style={{ marginTop: 0 }}>Shared bundles</h3>
        <p className="mlp-muted">
          Shipped with this instance — "a local directory of shared bundles ... no hosted
          registry in v1" (PLAN.md §12).
        </p>
        {localBundles.length === 0 ? (
          <p className="mlp-muted" data-testid="local-bundles-empty">
            No local bundles found.
          </p>
        ) : (
          <table className="mlp-table" data-testid="local-bundles-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Kind</th>
                <th>Description</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {localBundles.map((b) => (
                <tr key={b.filename} data-testid={`local-bundle-${b.filename}`}>
                  <td>{b.name ?? b.filename}</td>
                  <td>
                    <Pill tone="muted">{b.kind ?? "unknown"}</Pill>
                  </td>
                  <td className="mlp-muted" style={{ maxWidth: 420 }}>
                    {b.description}
                  </td>
                  <td>
                    <div className="mlp-actions">
                      <button
                        className="mlp-btn"
                        data-testid={`local-bundle-view-${b.filename}`}
                        disabled={busy !== null}
                        onClick={async () => {
                          const full = await client.getLocalBundle(b.filename);
                          setPasted(JSON.stringify(full, null, 2));
                          setParseError(null);
                        }}
                      >
                        View
                      </button>
                      <button
                        className="mlp-btn mlp-btn-primary"
                        data-testid={`local-bundle-import-${b.filename}`}
                        disabled={busy !== null}
                        onClick={() =>
                          void act(`local:${b.filename}`, () =>
                            client.importLocalBundle(b.filename, createProject),
                          )
                        }
                      >
                        {busy === `local:${b.filename}` ? "Importing…" : "Import"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* --- import a bundle from anywhere --- */}
      <section className="mlp-card">
        <h3 style={{ marginTop: 0 }}>Import a bundle</h3>
        <p className="mlp-muted">Paste a bundle's JSON, or upload the file you downloaded.</p>
        <textarea
          className="mlp-textarea mlp-mono"
          rows={8}
          value={pasted}
          data-testid="marketplace-paste"
          placeholder='{"bundle_version": 1, "kind": "template", "template": {...}}'
          onChange={(e) => {
            setPasted(e.target.value);
            setParseError(null);
          }}
        />
        {parseError && (
          <div className="mlp-error-text" data-testid="marketplace-parse-error">
            JSON error: {parseError}
          </div>
        )}
        <div className="mlp-actions" style={{ marginTop: 8, flexWrap: "wrap" }}>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            data-testid="marketplace-file"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onFile(file);
              e.target.value = "";
            }}
          />
          <button
            className="mlp-btn"
            data-testid="marketplace-file-trigger"
            onClick={() => fileInput.current?.click()}
          >
            Upload file…
          </button>
          <label className="mlp-inline-label">
            <input
              type="checkbox"
              checked={createProject}
              data-testid="marketplace-create-project"
              onChange={(e) => setCreateProject(e.target.checked)}
            />
            For a project bundle, also create the project
          </label>
          <button
            className="mlp-btn mlp-btn-primary"
            data-testid="marketplace-import"
            disabled={busy !== null || !pasted.trim()}
            onClick={importPasted}
          >
            {busy === "paste" ? "Importing…" : "Import"}
          </button>
        </div>
      </section>

      {/* --- export existing templates / judges --- */}
      <section className="mlp-card">
        <h3 style={{ marginTop: 0 }}>Export</h3>
        <p className="mlp-muted">
          A project's bundle (template + enrolled judges + config) downloads from that project's{" "}
          <strong>Export</strong> tab.
        </p>
        <h4>Templates</h4>
        <ul className="mlp-list" data-testid="export-templates-list">
          {templates.map((t) => (
            <li key={t.id} data-testid={`export-template-${t.id}`}>
              <span>
                {t.name} <span className="mlp-muted">v{t.version}</span>
              </span>
              <button
                className="mlp-btn"
                style={{ marginLeft: 10 }}
                data-testid={`export-template-download-${t.id}`}
                onClick={async () => {
                  try {
                    const bundle = await client.exportTemplateBundle(t.id);
                    download(`template-${t.name}-v${t.version}.json`, bundle);
                  } catch (e) {
                    setError(e instanceof Error ? e.message : String(e));
                  }
                }}
              >
                Download bundle
              </button>
            </li>
          ))}
        </ul>
        <h4>Judge configs</h4>
        {judges.length === 0 ? (
          <p className="mlp-muted" data-testid="export-judges-empty">
            No judge configs yet.
          </p>
        ) : (
          <ul className="mlp-list" data-testid="export-judges-list">
            {judges.map((j) => (
              <li key={j.id} data-testid={`export-judge-${j.id}`}>
                <span>
                  {j.name} <span className="mlp-muted">v{j.prompt_version}</span>
                </span>
                <button
                  className="mlp-btn"
                  style={{ marginLeft: 10 }}
                  data-testid={`export-judge-download-${j.id}`}
                  onClick={async () => {
                    try {
                      const bundle = await client.exportJudgeBundle(j.id);
                      download(`judge-${j.name}-v${j.prompt_version}.json`, bundle);
                    } catch (e) {
                      setError(e instanceof Error ? e.message : String(e));
                    }
                  }}
                >
                  Download bundle
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
