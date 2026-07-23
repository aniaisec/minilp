// New-project wizard (§11): pick/clone a template → guidelines → unit upload with
// per-row validation report → overlap K / agreement / gold config → create.
//
// Kept to a single scrolling form with numbered sections rather than a modal
// stepper: every field is visible, and the "create" action is gated on the few
// that are actually required. The clone step reuses the gallery templates the
// annotation view already renders, so a project always starts from a valid schema.

import { useEffect, useState } from "react";

import type { MiniLpClient } from "../../api/client";
import type { IngestReport, PayloadFormat, Template, TemplateSample } from "../../api/types";
import { exampleFor, missingRequiredFields } from "./payloadExamples";

export function Wizard({
  client,
  onCreated,
}: {
  client: MiniLpClient;
  onCreated: (projectId: number) => void;
}) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [cloneFirst, setCloneFirst] = useState(true);
  const [name, setName] = useState("");
  const [guidelines, setGuidelines] = useState("");
  const [k, setK] = useState(2);
  const [maxK, setMaxK] = useState(4);
  const [goldRatio, setGoldRatio] = useState(0.1);
  const [minReputation, setMinReputation] = useState(0);
  const [format, setFormat] = useState<PayloadFormat>("json");
  const [content, setContent] = useState("");
  const [contentTouched, setContentTouched] = useState(false);
  const [sample, setSample] = useState<TemplateSample | null>(null);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [batchName, setBatchName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<IngestReport | null>(null);

  useEffect(() => {
    client
      .listTemplates()
      .then((ts) => {
        setTemplates(ts);
        if (ts.length && templateId === null) setTemplateId(ts[0].id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  // When the template changes, load its saved/generated sample so the wizard can
  // show the expected shape (§11). Prefill the editor with the example unless the
  // user has already typed their own content.
  useEffect(() => {
    if (templateId === null) return;
    client
      .getTemplateSample(templateId)
      .then((s) => {
        setSample(s);
        if (!contentTouched) setContent(exampleFor(s, format));
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, templateId]);

  // Switching format re-prefills the example (until the user edits it themselves).
  useEffect(() => {
    if (sample && !contentTouched) setContent(exampleFor(sample, format));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [format]);

  const selected = templates.find((t) => t.id === templateId) ?? null;
  const nVariants = selected?.schema.variants?.values.length ?? 1;
  const divisible = k % nVariants === 0 && maxK % nVariants === 0;
  const missing = sample
    ? missingRequiredFields(content, format, sample.fields.required)
    : [];
  const canCreate = !!name && !!templateId && divisible && maxK >= k;

  async function create() {
    if (!templateId) return;
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      let tid = templateId;
      if (cloneFirst) {
        const clone = await client.cloneTemplate(templateId, `${name || "project"}-template`);
        tid = clone.id;
      }
      const project = await client.createProject({
        name,
        template_id: tid,
        labels_per_unit: k,
        max_labels_per_unit: maxK,
        gold_ratio: goldRatio,
        min_reputation: minReputation,
        guidelines_md: guidelines || null,
      });
      if (content.trim()) {
        const rep = await client.bulkUpload(
          project.id,
          content,
          format,
          batchName || undefined,
          uploadName || undefined,
        );
        setReport(rep);
      }
      onCreated(project.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mlp-stack-lg" style={{ maxWidth: "var(--content-lg)" }}>
      <h2>New project</h2>
      {error && <div className="mlp-card mlp-error">{error}</div>}

      <section className="mlp-card">
        <h3>1 · Template</h3>
        <label className="mlp-block-label">
          Start from
          <select
            value={templateId ?? ""}
            onChange={(e) => setTemplateId(Number(e.target.value))}
          >
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} (v{t.version}) {t.kind === "builtin" ? "· gallery" : "· custom"}
              </option>
            ))}
          </select>
        </label>
        <label className="mlp-check">
          <input
            type="checkbox"
            checked={cloneFirst}
            onChange={(e) => setCloneFirst(e.target.checked)}
          />
          Clone into an editable copy first (leaves the gallery original untouched)
        </label>
        {selected && (
          <p className="mlp-muted">
            {selected.description} · inputs: {selected.schema.inputs.map((i) => i.id).join(", ")}
            {nVariants > 1 && ` · ${nVariants} variants (${selected.schema.variants?.dimension})`}
          </p>
        )}
      </section>

      <section className="mlp-card">
        <h3>2 · Name & guidelines</h3>
        <label className="mlp-block-label">
          Project name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Q3 toxicity" />
        </label>
        <label className="mlp-block-label">
          Annotator guidelines (markdown)
          <textarea
            className="mlp-textarea"
            rows={5}
            value={guidelines}
            onChange={(e) => setGuidelines(e.target.value)}
            placeholder="Shown as a collapsible panel in the annotation view."
          />
        </label>
      </section>

      <section className="mlp-card">
        <h3>3 · Units</h3>
        <p className="mlp-muted">
          Upload a <strong>.json</strong> (array of unit objects) or <strong>.tsv</strong> (header
          row + one unit per line) file, or paste directly below. Rows missing a required field are
          rejected with their line number; valid rows are ingested.
        </p>

        <div className="mlp-filters" style={{ marginBottom: 10 }}>
          <label>
            File type
            <select value={format} onChange={(e) => setFormat(e.target.value as PayloadFormat)}>
              <option value="json">.json</option>
              <option value="tsv">.tsv</option>
            </select>
          </label>
          <label>
            Batch name
            <input value={batchName} onChange={(e) => setBatchName(e.target.value)} placeholder="first-drop" />
          </label>
          <label>
            Upload a file
            <input
              type="file"
              accept={format === "tsv" ? ".tsv,.txt" : ".json,.txt"}
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const text = await file.text();
                setContent(text);
                setContentTouched(true);
                setUploadName(file.name);
                if (file.name.endsWith(".tsv")) setFormat("tsv");
                else if (file.name.endsWith(".json")) setFormat("json");
              }}
            />
          </label>
        </div>

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
            rows={7}
            value={content}
            onChange={(e) => {
              setContent(e.target.value);
              setContentTouched(true);
              setUploadName(null);
            }}
          />
        </label>

        {sample && content.trim() && missing.length > 0 && (
          <div className="mlp-error-text">
            Missing required field{missing.length === 1 ? "" : "s"} in your data:{" "}
            {missing.join(", ")}
          </div>
        )}

        {report && (
          <div className="mlp-report">
            <p>
              Ingested <strong>{report.unit_count}</strong>, rejected{" "}
              <strong>{report.rejected_count}</strong>.
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
        <h3>4 · Overlap, agreement & golds</h3>
        <div className="mlp-grid-2">
          <label className="mlp-block-label">
            Labels per unit (K)
            <input type="number" min={1} value={k} onChange={(e) => setK(Number(e.target.value))} />
          </label>
          <label className="mlp-block-label">
            Max labels per unit
            <input
              type="number"
              min={1}
              value={maxK}
              onChange={(e) => setMaxK(Number(e.target.value))}
            />
          </label>
          <label className="mlp-block-label">
            Gold ratio
            <input
              type="number"
              step={0.05}
              min={0}
              max={1}
              value={goldRatio}
              onChange={(e) => setGoldRatio(Number(e.target.value))}
            />
          </label>
          <label className="mlp-block-label">
            Min reputation
            <input
              type="number"
              step={0.05}
              min={0}
              max={1}
              value={minReputation}
              onChange={(e) => setMinReputation(Number(e.target.value))}
            />
          </label>
        </div>
        {!divisible && (
          <p className="mlp-error-text">
            K and max-K must be divisible by the template's {nVariants} variant values (§2.7).
          </p>
        )}
        {maxK < k && <p className="mlp-error-text">Max labels must be ≥ K.</p>}
      </section>

      <div className="mlp-actions">
        <button
          className="mlp-btn mlp-btn-primary"
          disabled={!canCreate || busy}
          onClick={create}
        >
          {busy ? "Creating…" : "Create project"}
        </button>
      </div>
    </div>
  );
}
