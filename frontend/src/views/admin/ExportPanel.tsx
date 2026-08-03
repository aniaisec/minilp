// Export panel (§10, M6): pick a format, see the first rows, download the file.
//
// The preview matters more than it looks. An export you can't inspect is an
// export you find out is wrong after the training run — showing the first rows
// inline turns "did this work?" into a two-second read.

import { useCallback, useState } from "react";

import type { MiniLpClient } from "../../api/client";
import type { ExportFormat } from "../../api/types";

const FORMATS: { id: ExportFormat; label: string; blurb: string }[] = [
  {
    id: "labels",
    label: "Labels",
    blurb:
      "One row per unit: payload, the agreed final label per key, and per-label " +
      "provenance. Re-imports through “Add tasks” unchanged, so it doubles as a backup.",
  },
  {
    id: "raw",
    label: "Raw labels",
    blurb:
      "One row per label with raw + canonical + variant + annotator provenance — " +
      "the bias-study format (§9). Voided labels are included, flagged.",
  },
  {
    id: "preference",
    label: "Preference (RLHF)",
    blurb:
      "{prompt, chosen, rejected, meta} pairs for comparison projects. Units " +
      "without a clear winner are skipped rather than guessed at.",
  },
  {
    id: "sft",
    label: "SFT",
    blurb: "{input, output} pairs from a generation-style template's free-text answer.",
  },
];

const PREVIEW_ROWS = 3;

export function ExportPanel({
  client,
  projectId,
}: {
  client: MiniLpClient;
  projectId: number;
}) {
  const [format, setFormat] = useState<ExportFormat>("labels");
  const [preview, setPreview] = useState<string | null>(null);
  const [rowCount, setRowCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [bundleError, setBundleError] = useState<string | null>(null);
  const [bundleBusy, setBundleBusy] = useState(false);

  const run = useCallback(async () => {
    setBusy(true);
    setError(null);
    setPreview(null);
    setRowCount(null);
    try {
      const text = await client.fetchExport(projectId, format);
      const lines = text.split("\n").filter((l) => l.trim());
      setRowCount(lines.length);
      setPreview(
        lines
          .slice(0, PREVIEW_ROWS)
          .map((line) => {
            try {
              return JSON.stringify(JSON.parse(line), null, 2);
            } catch {
              return line;
            }
          })
          .join("\n\n"),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [client, projectId, format]);

  const download = async () => {
    try {
      const text = await client.fetchExport(projectId, format);
      const url = URL.createObjectURL(new Blob([text], { type: "application/x-ndjson" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `project-${projectId}-${format}.jsonl`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const active = FORMATS.find((f) => f.id === format)!;

  return (
    <div className="mlp-stack-lg" data-testid="export-panel">
      <section className="mlp-card">
        <h3 style={{ marginTop: 0 }}>Export (§10)</h3>
        <label className="mlp-block-label">
          Format
          <select
            value={format}
            data-testid="export-format"
            onChange={(e) => {
              setFormat(e.target.value as ExportFormat);
              setPreview(null);
              setRowCount(null);
              setError(null);
            }}
          >
            {FORMATS.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <p className="mlp-muted">{active.blurb}</p>

        <div className="mlp-actions">
          <button
            className="mlp-btn"
            disabled={busy}
            data-testid="export-preview"
            onClick={() => void run()}
          >
            {busy ? "Building…" : "Preview"}
          </button>
          <button
            className="mlp-btn mlp-btn-primary"
            data-testid="export-download"
            onClick={() => void download()}
          >
            Download .jsonl
          </button>
        </div>

        {error && (
          <div className="mlp-error-text" data-testid="export-error" style={{ marginTop: 10 }}>
            {error}
          </div>
        )}

        {rowCount !== null && (
          <p className="mlp-muted" data-testid="export-count" style={{ marginTop: 10 }}>
            {rowCount} row{rowCount === 1 ? "" : "s"}
            {rowCount > PREVIEW_ROWS ? ` — showing the first ${PREVIEW_ROWS}` : ""}.
          </p>
        )}
        {preview && (
          <pre className="mlp-code mlp-mono" data-testid="export-preview-body">
            {preview}
          </pre>
        )}
      </section>

      <section className="mlp-card" data-testid="bundle-export-panel">
        <h3 style={{ marginTop: 0 }}>Marketplace bundle (§12, M10)</h3>
        <p className="mlp-muted">
          The template, enrolled judge configs, and this project's config (guidelines, overlap,
          gold ratio, routing pipeline) as one shareable JSON bundle — a starter kit for a fresh
          instance. Units and labels stay behind; use the format above for those.
        </p>
        <div className="mlp-actions">
          <button
            className="mlp-btn"
            disabled={bundleBusy}
            data-testid="bundle-export-download"
            onClick={async () => {
              setBundleBusy(true);
              setBundleError(null);
              try {
                const bundle = await client.exportProjectBundle(projectId);
                const url = URL.createObjectURL(
                  new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" }),
                );
                const a = document.createElement("a");
                a.href = url;
                a.download = `project-${projectId}-bundle.json`;
                a.click();
                URL.revokeObjectURL(url);
              } catch (e) {
                setBundleError(e instanceof Error ? e.message : String(e));
              } finally {
                setBundleBusy(false);
              }
            }}
          >
            {bundleBusy ? "Building…" : "Download bundle"}
          </button>
        </div>
        {bundleError && (
          <div className="mlp-error-text" data-testid="bundle-export-error" style={{ marginTop: 10 }}>
            {bundleError}
          </div>
        )}
      </section>
    </div>
  );
}
