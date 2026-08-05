// Export panel (§10, M6): pick a format, see the first rows, download the file.
//
// The preview matters more than it looks. An export you can't inspect is an
// export you find out is wrong after the training run — showing the first rows
// inline turns "did this work?" into a two-second read.

import { useCallback, useState } from "react";

import { Button, Card, ErrorState } from "../../components/ui";
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
      <Card headingLevel={3} title="Export (§10)">
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
          <Button disabled={busy} data-testid="export-preview" onClick={() => void run()}>
            {busy ? "Building…" : "Preview"}
          </Button>
          <Button variant="primary" data-testid="export-download" onClick={() => void download()}>
            Download .jsonl
          </Button>
        </div>

        {error && (
          <ErrorState title="The export failed" inline data-testid="export-error">
            {error}
          </ErrorState>
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
      </Card>

      <Card
        headingLevel={3}
        data-testid="bundle-export-panel"
        title="Marketplace bundle (§12, M10)"
        description="The template, enrolled judge configs, and this project's config (guidelines, overlap, gold ratio, routing pipeline) as one shareable JSON bundle — a starter kit for a fresh instance. Units and labels stay behind; use the format above for those."
      >
        <div className="mlp-actions">
          <Button
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
          </Button>
        </div>
        {bundleError && (
          <ErrorState title="The bundle could not be built" inline data-testid="bundle-export-error">
            {bundleError}
          </ErrorState>
        )}
      </Card>
    </div>
  );
}
