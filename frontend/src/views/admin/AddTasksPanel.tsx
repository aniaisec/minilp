// "Add tasks" (§12 M6): the M5 upload surface, on a project that already exists.
//
// Same `units:bulk` endpoint, same per-row validation report — so growing a live
// project is the operation you already know, not a second one. The one addition
// is the **gold affordance**: a checkbox that appends `is_gold` / `gold_expected`
// to the example, plus the reminder that a gold in an appended batch enters
// measurement immediately (§6.1) — golds are not a project-creation-time decision.

import { useEffect, useState } from "react";

import type { MiniLpClient } from "../../api/client";
import type {
  Batch,
  IngestReport,
  PayloadFormat,
  Project,
  Template,
  TemplateSample,
} from "../../api/types";
import { exampleFor, missingRequiredFields } from "./payloadExamples";

/** The example upload, optionally showing how a row is marked as a gold. */
export function goldExample(
  base: string,
  format: PayloadFormat,
  inputIds: string[],
): string {
  const key = inputIds[0] ?? "answer";
  if (format === "tsv") {
    const lines = base.split("\n");
    if (lines.length < 2) return base;
    const header = `${lines[0]}\tis_gold\tgold_expected`;
    const rows = lines
      .slice(1)
      .map((row, i) => `${row}\t${i === 0 ? "true" : "false"}\t${i === 0 ? `{"${key}": "..."}` : ""}`);
    return [header, ...rows].join("\n");
  }
  try {
    const parsed = JSON.parse(base);
    if (!Array.isArray(parsed) || !parsed.length) return base;
    const rows = parsed.map((row, i) => {
      const payload = row && typeof row === "object" && "payload" in row ? row.payload : row;
      return i === 0
        ? { payload, is_gold: true, gold_expected: { [key]: "..." } }
        : { payload };
    });
    return JSON.stringify(rows, null, 2);
  } catch {
    return base;
  }
}

export function AddTasksPanel({
  client,
  projectId,
}: {
  client: MiniLpClient;
  projectId: number;
}) {
  const [project, setProject] = useState<Project | null>(null);
  const [template, setTemplate] = useState<Template | null>(null);
  const [sample, setSample] = useState<TemplateSample | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [format, setFormat] = useState<PayloadFormat>("json");
  const [withGolds, setWithGolds] = useState(false);
  const [content, setContent] = useState("");
  const [touched, setTouched] = useState(false);
  const [batchName, setBatchName] = useState("");
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<IngestReport | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const p = await client.getProject(projectId);
        const t = await client.getTemplate(p.template_id);
        const s = await client.getTemplateSample(p.template_id);
        const b = await client.listBatches(projectId);
        if (cancelled) return;
        setProject(p);
        setTemplate(t);
        setSample(s);
        setBatches(b);
        setBatchName(`batch-${b.length + 1}`);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, projectId]);

  // Re-prefill the example whenever the shape of it changes, until the admin
  // starts typing their own data.
  useEffect(() => {
    if (!sample || touched) return;
    const base = exampleFor(sample, format);
    setContent(
      withGolds ? goldExample(base, format, (template?.schema.inputs ?? []).map((i) => i.id)) : base,
    );
  }, [sample, format, withGolds, touched, template]);

  const missing = sample ? missingRequiredFields(content, format, sample.fields.required) : [];

  async function upload() {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const rep = await client.bulkUpload(
        projectId,
        content,
        format,
        batchName || undefined,
        uploadName || undefined,
      );
      setReport(rep);
      setBatches(await client.listBatches(projectId));
      setBatchName(`batch-${batches.length + 2}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!project) return <div className="mlp-card">{error ?? "Loading…"}</div>;

  return (
    <div className="mlp-stack-lg" data-testid="add-tasks-panel">
      <section className="mlp-card">
        <h3 style={{ marginTop: 0 }}>Add tasks</h3>
        <p className="mlp-muted">
          Appends a batch to this live project — no recreation, no downtime. Each
          new unit gets its own balanced set of {project.labels_per_unit} slots
          (§2.7), and joins the queue at its declared priority.
        </p>
        {error && <div className="mlp-error">{error}</div>}

        <div className="mlp-filters" style={{ marginBottom: 10 }}>
          <label>
            File type
            <select
              value={format}
              data-testid="add-format"
              onChange={(e) => setFormat(e.target.value as PayloadFormat)}
            >
              <option value="json">.json</option>
              <option value="tsv">.tsv</option>
            </select>
          </label>
          <label>
            Batch name
            <input
              value={batchName}
              data-testid="add-batch-name"
              onChange={(e) => setBatchName(e.target.value)}
            />
          </label>
          <label>
            Upload a file
            <input
              type="file"
              accept={format === "tsv" ? ".tsv,.txt" : ".json,.txt"}
              data-testid="add-file"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                setContent(await file.text());
                setTouched(true);
                setUploadName(file.name);
                if (file.name.endsWith(".tsv")) setFormat("tsv");
                else if (file.name.endsWith(".json")) setFormat("json");
              }}
            />
          </label>
        </div>

        <label className="mlp-check">
          <input
            type="checkbox"
            checked={withGolds}
            data-testid="add-with-golds"
            onChange={(e) => {
              setWithGolds(e.target.checked);
              setTouched(false); // re-prefill the example in the new shape
            }}
          />
          Include gold questions in this batch
        </label>
        {withGolds && (
          <p className="mlp-muted mlp-field-hint" data-testid="gold-help">
            A row with <code>is_gold: true</code> and a <code>gold_expected</code>{" "}
            answer becomes a gold immediately: injected at this project's gold ratio
            ({project.gold_ratio}), graded on submit, and feeding rolling gold accuracy
            and reputation (§6.1). Golds stay indistinguishable in the annotation UI —
            keep their payloads looking like everything else. A row flagged gold with
            no <code>gold_expected</code> is rejected, because it would measure nothing.
          </p>
        )}

        {sample && (
          <p className="mlp-muted" style={{ fontSize: 13 }}>
            Required field{sample.fields.required.length === 1 ? "" : "s"}:{" "}
            <span className="mlp-mono">{sample.fields.required.join(", ") || "none"}</span>
            {sample.fields.optional.length > 0 && (
              <>
                {" "}· optional: <span className="mlp-mono">{sample.fields.optional.join(", ")}</span>
              </>
            )}
          </p>
        )}

        <label className="mlp-block-label">
          Data ({format})
          <textarea
            className="mlp-textarea mlp-mono"
            rows={10}
            value={content}
            data-testid="add-content"
            onChange={(e) => {
              setContent(e.target.value);
              setTouched(true);
              setUploadName(null);
            }}
          />
        </label>

        {content.trim() && missing.length > 0 && (
          <div className="mlp-error-text" data-testid="add-missing">
            Missing required field{missing.length === 1 ? "" : "s"}: {missing.join(", ")}
          </div>
        )}

        <div className="mlp-actions" style={{ marginTop: 10 }}>
          <button
            className="mlp-btn mlp-btn-primary"
            disabled={busy || !content.trim()}
            data-testid="add-upload"
            onClick={() => void upload()}
          >
            {busy ? "Uploading…" : "Add tasks"}
          </button>
        </div>

        {report && (
          <div className="mlp-report" data-testid="add-report">
            <p>
              Ingested <strong>{report.unit_count}</strong>, rejected{" "}
              <strong>{report.rejected_count}</strong> into batch #{report.batch_id}.
            </p>
            {report.rejected_rows.length > 0 && (
              <ul className="mlp-reject-list">
                {report.rejected_rows.map((r) => (
                  <li key={r.row}>
                    row {r.row}: {r.errors.join("; ")}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      <section className="mlp-card">
        <h3 style={{ marginTop: 0 }}>Batches</h3>
        <table className="mlp-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Name</th>
              <th>Source</th>
              <th>Units</th>
              <th>Rejected</th>
            </tr>
          </thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.id}>
                <td>{b.id}</td>
                <td>{b.name ?? "—"}</td>
                <td className="mlp-muted">{b.source_filename ?? "—"}</td>
                <td>{b.unit_count}</td>
                <td>{b.rejected_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
