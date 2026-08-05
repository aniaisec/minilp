// Marketplace (§12, M10): browse the bundles shipped with this instance, import
// one with a click, paste/upload a bundle from somewhere else, and download a
// bundle for anything you already have — a template, a judge config, or (from
// each project's Export tab) a whole project starter kit.
//
// "No hosted registry in v1" (PLAN.md §12) is the whole shape of this panel: the
// left side reads a directory that ships with the repo, the right side is a
// generic import/export surface that works with any bundle from anywhere.

import { useCallback, useEffect, useRef, useState } from "react";

import { Button, Card, EmptyState, ErrorState, Table } from "../../components/ui";
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
      <Card
        title="Marketplace (§12)"
        description={
          <>
            Export a template, judge config, or project as a shareable JSON bundle; import
            re-runs the exact validation a hand-authored one goes through, so an imported bundle
            validates and previews identically. A judge-config bundle never carries a credential
            — only the <em>name</em> of an environment variable the server reads at call time.
          </>
        }
      >
        {error && (
          <ErrorState title="The import failed" inline data-testid="marketplace-error">
            {error}
          </ErrorState>
        )}

        {result && (
          <div className="mlp-muted" data-testid="marketplace-result" style={{ marginTop: 6 }}>
            Imported: {resultSummary(result)}.
          </div>
        )}
      </Card>

      {/* --- shipped bundles --- */}
      <Card
        title="Shared bundles"
        description={`Shipped with this instance — "a local directory of shared bundles ... no hosted registry in v1" (PLAN.md §12).`}
      >
        <Table
          caption="Bundles shipped with this instance"
          data-testid="local-bundles-table"
          columns={["Name", "Kind", "Description", { srLabel: "Actions" }]}
          isEmpty={localBundles.length === 0}
          empty={
            <EmptyState title="No local bundles found" data-testid="local-bundles-empty">
              This instance ships no shared bundles. You can still import one by pasting or
              uploading its JSON below.
            </EmptyState>
          }
        >
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
                  <Button
                    variant="ghost"
                    size="sm"
                    data-testid={`local-bundle-view-${b.filename}`}
                    disabled={busy !== null}
                    onClick={async () => {
                      const full = await client.getLocalBundle(b.filename);
                      setPasted(JSON.stringify(full, null, 2));
                      setParseError(null);
                    }}
                  >
                    View
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    data-testid={`local-bundle-import-${b.filename}`}
                    disabled={busy !== null}
                    onClick={() =>
                      void act(`local:${b.filename}`, () =>
                        client.importLocalBundle(b.filename, createProject),
                      )
                    }
                  >
                    {busy === `local:${b.filename}` ? "Importing…" : "Import"}
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </Table>
      </Card>

      {/* --- import a bundle from anywhere --- */}
      <Card
        title="Import a bundle"
        description="Paste a bundle's JSON, or upload the file you downloaded."
      >
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
          <ErrorState
            title="That is not valid JSON"
            inline
            data-testid="marketplace-parse-error"
          >
            JSON error: {parseError}
          </ErrorState>
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
          <Button
            data-testid="marketplace-file-trigger"
            onClick={() => fileInput.current?.click()}
          >
            Upload file…
          </Button>
          <label className="mlp-inline-label">
            <input
              type="checkbox"
              checked={createProject}
              data-testid="marketplace-create-project"
              onChange={(e) => setCreateProject(e.target.checked)}
            />
            For a project bundle, also create the project
          </label>
          <Button
            variant="primary"
            data-testid="marketplace-import"
            disabled={busy !== null || !pasted.trim()}
            onClick={importPasted}
          >
            {busy === "paste" ? "Importing…" : "Import"}
          </Button>
        </div>
      </Card>

      {/* --- export existing templates / judges --- */}
      <Card
        title="Export"
        description={
          <>
            A project's bundle (template + enrolled judges + config) downloads from that
            project's <strong>Export</strong> tab.
          </>
        }
      >
        <h3>Templates</h3>
        {templates.length === 0 ? (
          <EmptyState title="No templates yet" inline data-testid="export-templates-empty">
            Build or import a template and it becomes exportable here.
          </EmptyState>
        ) : (
          <ul className="mlp-list" data-testid="export-templates-list">
            {templates.map((t) => (
              <li key={t.id} data-testid={`export-template-${t.id}`}>
                <span>
                  {t.name} <span className="mlp-muted">v{t.version}</span>
                </span>
                <Button
                  variant="ghost"
                  size="sm"
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
                </Button>
              </li>
            ))}
          </ul>
        )}
        <h3>Judge configs</h3>
        {judges.length === 0 ? (
          <EmptyState title="No judge configs yet" inline data-testid="export-judges-empty">
            Create one from a project's Judges section and it becomes exportable here.
          </EmptyState>
        ) : (
          <ul className="mlp-list" data-testid="export-judges-list">
            {judges.map((j) => (
              <li key={j.id} data-testid={`export-judge-${j.id}`}>
                <span>
                  {j.name} <span className="mlp-muted">v{j.prompt_version}</span>
                </span>
                <Button
                  variant="ghost"
                  size="sm"
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
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
