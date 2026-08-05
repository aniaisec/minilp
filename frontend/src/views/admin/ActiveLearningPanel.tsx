// Active-learning tab (M9, §8/§11: "AL iteration curves"). Three things, in
// the order the loop actually runs: what to label next (informativeness
// ranking), re-enrolling a fine-tuned checkpoint as the next version, and the
// eval curve that answers "did the last iteration actually help".
//
// Nothing here trains a model — "you train, MiniLP loops" (§8). This panel
// only ever reads/composes numbers the quality and judge subsystems already
// keep: consensus entropy, gold accuracy, spend.

import { useCallback, useEffect, useState } from "react";

import { Button, Card, EmptyState, ErrorState, Table } from "../../components/ui";
import type { MiniLpClient } from "../../api/client";
import type { ActiveLearningBatch, IterationCurve } from "../../api/types";
import { StatCard } from "./widgets";

const pct = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `${Math.round(n * 100)}%`;

const money = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `$${n.toFixed(n < 0.01 && n > 0 ? 5 : 4)}`;

export function ActiveLearningPanel({
  client,
  projectId,
}: {
  client: MiniLpClient;
  projectId: number;
}) {
  const [names, setNames] = useState<string[]>([]);
  const [selectedName, setSelectedName] = useState<string>("");
  const [curve, setCurve] = useState<IterationCurve | null>(null);
  const [batch, setBatch] = useState<ActiveLearningBatch | null>(null);
  const [limit, setLimit] = useState(20);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const loadJudges = useCallback(async () => {
    const p = await client.listProjectJudges(projectId).catch(() => ({ judges: [] }));
    // A "checkpoint line" is a judge-config name — the same student re-enrolled
    // under one name across versions (§8). Model judges' display names carry
    // "name vN"; strip the version to get the line's name.
    const lineNames = Array.from(
      new Set(p.judges.map((j) => j.display_name.replace(/\s+v\d+$/, ""))),
    );
    setNames(lineNames);
    setSelectedName((current) => current || lineNames[0] || "");
  }, [client, projectId]);

  useEffect(() => {
    void loadJudges();
  }, [loadJudges]);

  const loadCurve = useCallback(
    async (name: string) => {
      if (!name) {
        setCurve(null);
        return;
      }
      setError(null);
      try {
        setCurve(await client.iterationCurve(projectId, name));
      } catch (e) {
        setCurve(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [client, projectId],
  );

  useEffect(() => {
    void loadCurve(selectedName);
  }, [selectedName, loadCurve]);

  const latestJudgeConfigId = curve?.iterations.at(-1)?.judge_config_id;

  const loadBatch = useCallback(async () => {
    setBusy("batch");
    setError(null);
    try {
      setBatch(
        await client.activeLearningBatch(projectId, { limit, judgeConfigId: latestJudgeConfigId }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, [client, projectId, limit, latestJudgeConfigId]);

  return (
    <div className="mlp-stack-lg" data-testid="al-panel">
      {error && (
        <ErrorState title="The last active-learning call failed" inline data-testid="al-error">
          {error}
        </ErrorState>
      )}

      {/* --- eval curve --- */}
      <Card
        headingLevel={3}
        title="Iteration eval curve (§8)"
        description={
          <>
            A checkpoint re-enrolled under the same name is a new <em>iteration</em> — its{" "}
            <code>prompt_version</code> reused as the loop's own counter, no second one kept. Gold
            accuracy and agreement against the decided answer (<code>final_labels</code>) are the
            eval curve.
          </>
        }
      >
        {names.length === 0 ? (
          <EmptyState title="No checkpoint registered yet" data-testid="al-no-checkpoints">
            Register a checkpoint below to start a loop. Each re-registration under the same name
            becomes the next iteration on this curve.
          </EmptyState>
        ) : (
          <div className="mlp-actions" style={{ marginBottom: 10 }}>
            <label className="mlp-inline-label">
              Checkpoint line
              <select
                value={selectedName}
                data-testid="al-line-select"
                onChange={(e) => setSelectedName(e.target.value)}
              >
                {names.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        {curve && curve.iterations.length > 0 && (
          <>
            <div className="mlp-stats">
              <StatCard
                label="Latest gold accuracy"
                value={pct(curve.iterations.at(-1)?.gold_accuracy.rate)}
                sub={`${curve.iterations.length} iteration(s)`}
              />
              <StatCard
                label="Latest vs. decided"
                value={pct(curve.iterations.at(-1)?.agreement_vs_final.rate)}
                sub="agreement with final_labels"
              />
              <StatCard label="Human minutes on this project" value={curve.human_minutes} />
            </div>
            <Table
              className="mlp-table-spaced"
              caption="Eval curve — one row per checkpoint iteration"
              data-testid="al-iterations-table"
              columns={[
                "#",
                "Model",
                "Gold accuracy",
                "Agreement vs. decided",
                "Labels",
                "Spend",
              ]}
            >
              {curve.iterations.map((p) => (
                <tr key={p.judge_config_id} data-testid={`al-iter-${p.iteration}`}>
                  <td className="mlp-mono">v{p.iteration}</td>
                  <td className="mlp-mono">
                    {p.provider} / {p.model_id}
                  </td>
                  <td>
                    {pct(p.gold_accuracy.rate)}
                    {p.gold_accuracy.total > 0 && (
                      <span className="mlp-muted">
                        {" "}
                        ({p.gold_accuracy.passes}/{p.gold_accuracy.total})
                      </span>
                    )}
                  </td>
                  <td>
                    {pct(p.agreement_vs_final.rate)}
                    {p.agreement_vs_final.comparisons > 0 && (
                      <span className="mlp-muted">
                        {" "}
                        ({p.agreement_vs_final.agreements}/{p.agreement_vs_final.comparisons})
                      </span>
                    )}
                  </td>
                  <td>{p.label_count}</td>
                  <td>{money(p.spend?.cost_usd)}</td>
                </tr>
              ))}
            </Table>
          </>
        )}
      </Card>

      {/* --- register the next checkpoint --- */}
      <Card
        headingLevel={3}
        title="Register a checkpoint (§8 step 4)"
        description={
          <>
            Fine-tune externally, then register the checkpoint here — this writes the next
            judge-config version under the name and enrolls it in one call, exactly like{" "}
            <code>POST /judges/{"{id}"}:version</code> followed by <code>:attach</code>. A local
            or fine-tuned checkpoint is the <code>openai_compatible</code> provider with its{" "}
            <code>base_url</code> pointed at your server — no new provider code.
          </>
        }
        actions={
          <Button data-testid="al-toggle-form" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "Register checkpoint…"}
          </Button>
        }
      >
        {showForm && (
          <CheckpointForm
            defaultName={selectedName}
            busy={busy !== null}
            onRegister={async (body) => {
              setBusy("register");
              setError(null);
              try {
                await client.registerCheckpoint(projectId, body);
                setShowForm(false);
                setSelectedName(body.name);
                await loadJudges();
                await loadCurve(body.name);
              } catch (e) {
                setError(e instanceof Error ? e.message : String(e));
              } finally {
                setBusy(null);
              }
            }}
          />
        )}
      </Card>

      {/* --- next batch to label --- */}
      <Card
        headingLevel={3}
        title="Next batch (§8 step 1)"
        description="Ranked by informativeness: ensemble disagreement, vote entropy, and — when a checkpoint line above has a judge — that model's own low confidence. Already-finalized units are not scored; there is nothing left to be informative about."
      >
        <div className="mlp-actions" style={{ alignItems: "center" }}>
          <label className="mlp-inline-label">
            Batch size
            <input
              type="number"
              min={1}
              max={500}
              value={limit}
              data-testid="al-batch-limit"
              onChange={(e) => setLimit(Math.max(1, Number(e.target.value) || 1))}
              style={{ width: 80 }}
            />
          </label>
          <Button
            variant="primary"
            data-testid="al-load-batch"
            disabled={busy !== null}
            onClick={() => void loadBatch()}
          >
            {busy === "batch" ? "Ranking…" : "Rank next batch"}
          </Button>
        </div>

        {batch && (
          <>
            <p className="mlp-muted" style={{ marginTop: 10 }} data-testid="al-batch-summary">
              {batch.pool_size} unfinalized unit(s) in the pool
              {batch.dropped_by_dedupe > 0 && `, ${batch.dropped_by_dedupe} dropped as near-duplicates`}
              .
            </p>
            <Table
              caption="Units ranked by informativeness, most informative first"
              data-testid="al-batch-table"
              columns={["Unit", "Disagreement", "Entropy", "Confidence", "Score"]}
              isEmpty={batch.units.length === 0}
              empty={
                <EmptyState title="Nothing left to rank" data-testid="al-batch-empty">
                  Every unit in this project is finalized, so there is nothing left for a label to
                  be informative about.
                </EmptyState>
              }
            >
              {batch.units.map((u) => (
                <tr key={u.unit_id}>
                  <td className="mlp-mono">#{u.unit_id}</td>
                  <td>{u.disagreement === null ? "—" : u.disagreement.toFixed(2)}</td>
                  <td>{u.entropy === null ? "—" : u.entropy.toFixed(2)}</td>
                  <td>{u.confidence === null ? "—" : u.confidence.toFixed(2)}</td>
                  <td>
                    <strong>{u.score.toFixed(2)}</strong>
                  </td>
                </tr>
              ))}
            </Table>
          </>
        )}
      </Card>
    </div>
  );
}

// --- the checkpoint-registration form ----------------------------------------

function CheckpointForm({
  defaultName,
  busy,
  onRegister,
}: {
  defaultName: string;
  busy: boolean;
  onRegister: (body: {
    name: string;
    provider: string;
    model_id: string;
    params: Record<string, unknown> | null;
    budget: Record<string, number> | null;
  }) => Promise<void>;
}) {
  const [name, setName] = useState(defaultName || "local-ft");
  const [provider, setProvider] = useState("mock");
  const [modelId, setModelId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [maxLabels, setMaxLabels] = useState("");

  const submit = () => {
    const params: Record<string, unknown> = {};
    if (baseUrl.trim()) params.base_url = baseUrl.trim();
    const budget: Record<string, number> = {};
    if (maxLabels.trim()) budget.max_labels = Number(maxLabels);
    void onRegister({
      name: name.trim(),
      provider,
      model_id: modelId.trim(),
      params: Object.keys(params).length ? params : null,
      budget: Object.keys(budget).length ? budget : null,
    });
  };

  return (
    <div className="mlp-stack" style={{ marginTop: 12 }} data-testid="al-checkpoint-form">
      <label className="mlp-block-label">
        Checkpoint line (name)
        <input
          value={name}
          data-testid="al-ckpt-name"
          placeholder="local-ft"
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label className="mlp-block-label">
        Provider
        <select
          value={provider}
          data-testid="al-ckpt-provider"
          onChange={(e) => setProvider(e.target.value)}
        >
          <option value="mock">mock (try it out — free, deterministic)</option>
          <option value="openai_compatible">openai_compatible (local / fine-tuned server)</option>
          <option value="anthropic">anthropic</option>
          <option value="openai">openai</option>
        </select>
      </label>
      <label className="mlp-block-label">
        Model id
        <input
          value={modelId}
          data-testid="al-ckpt-model"
          placeholder="mock-1"
          onChange={(e) => setModelId(e.target.value)}
        />
      </label>
      {provider === "openai_compatible" && (
        <label className="mlp-block-label">
          Base URL
          <input
            value={baseUrl}
            data-testid="al-ckpt-base-url"
            placeholder="http://localhost:8000/v1"
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </label>
      )}
      <label className="mlp-inline-label">
        Max labels this version
        <input
          value={maxLabels}
          data-testid="al-ckpt-max-labels"
          onChange={(e) => setMaxLabels(e.target.value)}
          style={{ width: 100 }}
        />
      </label>
      <div className="mlp-actions">
        <button
          className="mlp-btn mlp-btn-primary"
          data-testid="al-ckpt-submit"
          disabled={busy || !name.trim() || !modelId.trim()}
          onClick={submit}
        >
          Register &amp; enroll
        </button>
      </div>
    </div>
  );
}
