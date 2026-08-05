// Judges tab (M7, §7.1/§11): enroll a model judge, price a run before paying for
// it, run it, and watch spend against the cap.
//
// The interaction order is the whole point. "Dry run" is the primary button and
// "Run" is deliberately not — you should find out a run costs $40 *before* it
// costs $40. Everything else on this panel exists to make the two numbers that
// matter legible: what a judge has spent, and how close that is to its cap.
//
// Blinding note (§3, DESIGN.md postmortem 2): this panel is admin-only and shows
// model names freely. Nothing here is ever rendered in the annotation view.

import { useCallback, useEffect, useState } from "react";

import { Button, Card, EmptyState, ErrorState, Table } from "../../components/ui";
import type { MiniLpClient } from "../../api/client";
import type {
  Costs,
  EnrolledJudge,
  JudgeBudget,
  JudgeConfig,
  JudgeRunResponse,
  JudgeRunRow,
} from "../../api/types";
import { Bar, StatCard } from "./widgets";

const PROVIDER_BLURB: Record<string, string> = {
  mock: "Deterministic, offline, free. Answers from a hash of the prompt — for trying the loop out.",
  anthropic: "Anthropic Messages API. Key read from $ANTHROPIC_API_KEY on the server.",
  openai: "OpenAI Chat Completions. Key read from $OPENAI_API_KEY on the server.",
  openai_compatible:
    "Any server speaking the OpenAI shape — vLLM, llama.cpp, Ollama, or your own " +
    "fine-tuned checkpoint. Set params.base_url; a key is usually not needed.",
};

const money = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `$${n.toFixed(n < 0.01 && n > 0 ? 5 : 4)}`;

const pct = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `${Math.round(n * 100)}%`;

/** How much of a judge's cap is used — the number the panel exists to show. */
function capUsage(budget: JudgeBudget | null | undefined, spend: EnrolledJudge["spend"]) {
  if (!budget || !spend) return null;
  const pairs: [string, number, number][] = [];
  if (budget.project_usd) pairs.push(["project $", spend.cost_usd, budget.project_usd]);
  if (budget.daily_usd) pairs.push(["daily $", spend.daily_usd, budget.daily_usd]);
  if (budget.max_tokens) pairs.push(["tokens", spend.tokens, budget.max_tokens]);
  if (budget.max_labels) pairs.push(["labels", spend.labels, budget.max_labels]);
  return pairs.length ? pairs : null;
}

function stopReasonText(reason: string | null): string {
  switch (reason) {
    case "exhausted":
      return "no eligible slots left";
    case "limit":
      return "hit this run's slot limit";
    case "budget_project":
      return "stopped — project budget cap reached";
    case "budget_daily":
      return "stopped — daily budget cap reached";
    case "budget_tokens":
      return "stopped — token cap reached";
    case "budget_labels":
      return "stopped — label cap reached";
    case "provider_error":
      return "stopped — the provider kept failing";
    default:
      return reason ?? "—";
  }
}

export function JudgesPanel({
  client,
  projectId,
}: {
  client: MiniLpClient;
  projectId: number;
}) {
  const [enrolled, setEnrolled] = useState<EnrolledJudge[]>([]);
  const [configs, setConfigs] = useState<JudgeConfig[]>([]);
  const [providers, setProviders] = useState<string[]>([]);
  const [runs, setRuns] = useState<JudgeRunRow[]>([]);
  const [costs, setCosts] = useState<Costs | null>(null);
  const [report, setReport] = useState<JudgeRunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [limit, setLimit] = useState(25);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [p, c, r, k] = await Promise.all([
        client.listProjectJudges(projectId),
        client.listJudges().catch(() => [] as JudgeConfig[]),
        client.listJudgeRuns(projectId).catch(() => [] as JudgeRunRow[]),
        client.getCosts(projectId).catch(() => null),
      ]);
      setEnrolled(p.judges);
      setConfigs(c);
      setRuns(r);
      setCosts(k);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [client, projectId]);

  useEffect(() => {
    void load();
    client
      .listProviders()
      .then((r) => setProviders(r.providers))
      .catch(() => setProviders(["mock"]));
  }, [client, load]);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const run = (dry: boolean, judgeId?: number) =>
    act(dry ? "dry" : "run", async () => {
      const result = await client.runJudges(projectId, {
        dry_run: dry,
        limit,
        judge_config_id: judgeId,
      });
      setReport(result);
    });

  const unenrolled = configs.filter(
    (c) => !enrolled.some((e) => e.judge_config_id === c.id),
  );

  return (
    <div className="mlp-stack-lg" data-testid="judges-panel">
      {error && (
        <ErrorState title="The last judge action failed" inline data-testid="judges-error">
          {error}
        </ErrorState>
      )}

      {/* --- enrolled judges + run controls --- */}
      <Card
        headingLevel={3}
        title="Model judges (§7.1)"
        description={
          <>
            A judge is enrolled as a <code>kind=model</code> annotator and pulls work through the
            same <code>next</code>/<code>submit</code> loop humans use — so leasing, gold
            injection, variant balance and the annotator-unit exclusion all apply to it
            unchanged.
          </>
        }
      >
        <Table
          caption="Judges enrolled on this project, with spend against budget"
          data-testid="judges-table"
          columns={[
            "Judge",
            "Provider / model",
            "Labels",
            "Spent",
            "Budget",
            { srLabel: "Actions" },
          ]}
          isEmpty={enrolled.length === 0}
          empty={
            <EmptyState title="No judges enrolled yet" data-testid="judges-empty">
              Enroll a judge below to have a model pull work through the same loop your human
              annotators use. Nothing runs until you start a run.
            </EmptyState>
          }
        >
          {enrolled.map((j) => {
            const usage = capUsage(j.budget, j.spend);
            return (
              <tr key={j.judge_config_id} data-testid={`judge-row-${j.judge_config_id}`}>
                <td>
                  <strong>{j.display_name}</strong>
                  <div className="mlp-muted mlp-mono" style={{ fontSize: "0.85em" }}>
                    annotator #{j.annotator_id ?? "—"}
                  </div>
                </td>
                <td className="mlp-mono">
                  {j.provider}
                  <div className="mlp-muted" style={{ fontSize: "0.85em" }}>
                    {j.model_id}
                  </div>
                </td>
                <td>{j.spend?.labels ?? 0}</td>
                <td>
                  {j.priced ? (
                    money(j.spend?.cost_usd)
                  ) : (
                    <span title="No price is known for this model — this is not $0.00, it is unknown.">
                      unpriced
                    </span>
                  )}
                  {j.spend && j.spend.cache_hits > 0 && (
                    <div className="mlp-muted" style={{ fontSize: "0.85em" }}>
                      {j.spend.cache_hits} cached
                    </div>
                  )}
                </td>
                <td style={{ minWidth: 160 }}>
                  {usage ? (
                    usage.map(([label, used, cap]) => (
                      <Bar
                        key={label}
                        frac={cap ? used / cap : 0}
                        color={used / cap >= 1 ? "var(--danger, #c33)" : "var(--accent)"}
                        label={`${label} ${used <= 1 ? used.toFixed(4) : Math.round(used)} / ${cap}`}
                      />
                    ))
                  ) : (
                    <span className="mlp-muted">uncapped</span>
                  )}
                </td>
                <td>
                  <Button
                    variant="ghost"
                    size="sm"
                    data-testid={`detach-${j.judge_config_id}`}
                    disabled={busy !== null}
                    onClick={() =>
                      void act("detach", () => client.detachJudge(projectId, j.judge_config_id))
                    }
                  >
                    Detach
                  </Button>
                </td>
              </tr>
            );
          })}
        </Table>

        <div className="mlp-actions" style={{ marginTop: 12, alignItems: "center" }}>
          <label className="mlp-inline-label">
            Slots per run
            <input
              type="number"
              min={1}
              max={5000}
              value={limit}
              data-testid="judge-limit"
              onChange={(e) => setLimit(Math.max(1, Number(e.target.value) || 1))}
              style={{ width: 90 }}
            />
          </label>
          <Button
            variant="primary"
            data-testid="judge-dry-run"
            disabled={busy !== null || enrolled.length === 0}
            onClick={() => void run(true)}
          >
            {busy === "dry" ? "Pricing…" : "Dry run (estimate cost)"}
          </Button>
          <Button
            data-testid="judge-run"
            disabled={busy !== null || enrolled.length === 0}
            onClick={() => void run(false)}
          >
            {busy === "run" ? "Running…" : "Run judges"}
          </Button>
        </div>
        <p className="mlp-muted" style={{ marginTop: 6 }}>
          A dry run assembles the real prompts and prices them without calling the provider,
          then releases every slot it looked at. Find out what a run costs before it costs it.
        </p>
      </Card>

      {/* --- last run report --- */}
      {report && (
        <Card
          headingLevel={3}
          data-testid="run-report"
          title={report.dry_run ? "Estimate" : "Run report"}
          description={
            report.dry_run
              ? "Priced against the real prompts. Nothing was charged and every slot was released."
              : "What the last live run actually did."
          }
        >
          <div className="mlp-stats">
            <StatCard
              label={report.dry_run ? "Estimated cost" : "Cost"}
              value={money(report.dry_run ? report.estimated_cost_usd : report.cost_usd)}
              sub={report.dry_run ? "not charged" : undefined}
            />
            <StatCard label="Labels written" value={report.labels_written} />
            <StatCard
              label="Slots looked at"
              value={report.runs.reduce((n, r) => n + r.slots_attempted, 0)}
            />
            <StatCard
              label="Cache hits"
              value={report.runs.reduce((n, r) => n + r.cache_hits, 0)}
              sub="never paid for twice"
            />
          </div>
          <ul className="mlp-list" style={{ marginTop: 10 }}>
            {report.runs.map((r, i) => (
              <li key={r.run_id ?? i} data-testid={`run-line-${r.judge_config_id}`}>
                judge #{r.judge_config_id}: <strong>{stopReasonText(r.stopped_reason)}</strong>
                {r.webhooks_fired > 0 && ` · ${r.webhooks_fired} webhook(s) fired`}
                {r.errors.length > 0 && (
                  <details style={{ marginTop: 4 }}>
                    <summary className="mlp-muted">{r.errors.length} problem(s)</summary>
                    <ul className="mlp-list mlp-mono" style={{ fontSize: "0.85em" }}>
                      {r.errors.slice(0, 10).map((e, j) => (
                        <li key={j}>
                          [{e.stage}] {e.unit_id ? `unit ${e.unit_id}: ` : ""}
                          {e.error}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* --- costs --- */}
      {costs && costs.judges.length > 0 && (
        <Card headingLevel={3} data-testid="costs-panel" title="Cost (§5 /analytics/costs)">
          <div className="mlp-stats">
            <StatCard label="Judge spend" value={money(costs.totals.cost_usd)} />
            <StatCard
              label="$ / judge label"
              value={money(costs.totals.cost_per_judge_label)}
              sub={`${costs.totals.judge_labels} judge · ${costs.totals.human_labels} human`}
            />
            <StatCard label="Cache hit rate" value={pct(costs.totals.cache_hit_rate)} />
            <StatCard label="Tokens" value={costs.totals.tokens.toLocaleString()} />
          </div>
          <Table
            caption="Per-judge cost and latency"
            className="mlp-table-spaced"
            columns={["Judge", "Labels", "Cost", "$/label", "Cache", "Avg latency"]}
          >
            {costs.judges.map((j) => (
              <tr key={j.annotator_id}>
                <td>{j.display_name}</td>
                <td>{j.labels}</td>
                <td>{money(j.cost_usd)}</td>
                <td>{money(j.cost_per_label)}</td>
                <td>{pct(j.cache_hit_rate)}</td>
                <td>{j.avg_latency_ms === null ? "—" : `${Math.round(j.avg_latency_ms)} ms`}</td>
              </tr>
            ))}
          </Table>
        </Card>
      )}

      {/* --- enroll an existing config / create a new one --- */}
      <Card
        headingLevel={3}
        title="Enroll a judge"
        actions={
          <Button data-testid="toggle-judge-form" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "New judge config…"}
          </Button>
        }
      >
        {unenrolled.length > 0 ? (
          <div className="mlp-actions" style={{ flexWrap: "wrap" }}>
            {unenrolled.map((c) => (
              <Button
                key={c.id}
                data-testid={`attach-${c.id}`}
                disabled={busy !== null}
                onClick={() => void act("attach", () => client.attachJudge(projectId, c.id))}
              >
                + {c.name} v{c.prompt_version}{" "}
                <span className="mlp-muted">({c.provider})</span>
              </Button>
            ))}
          </div>
        ) : (
          <EmptyState title="No unenrolled judge configs" inline data-testid="unenrolled-empty">
            Every judge config you have is already on this project. Create a new one to add
            another.
          </EmptyState>
        )}
        {showForm && (
          <JudgeForm
            providers={providers}
            busy={busy !== null}
            onCreate={async (body, attach) => {
              await act("create", async () => {
                const created = await client.createJudge(body);
                if (attach) await client.attachJudge(projectId, created.id);
                setShowForm(false);
              });
            }}
          />
        )}
      </Card>

      {/* --- run history --- */}
      {runs.length > 0 && (
        <Card
          headingLevel={3}
          data-testid="run-history"
          title="Run history"
          description="Estimates and live runs sit side by side on purpose — it is the only honest way to check whether the estimate was any good."
        >
          <Table
            caption="Judge runs, most recent first"
            columns={["#", "Kind", "Judge", "Labels", "Cost", "Ended"]}
          >
            {runs.slice(0, 15).map((r) => (
              <tr key={r.id}>
                <td className="mlp-mono">{r.id}</td>
                <td>{r.dry_run ? "estimate" : "live"}</td>
                <td className="mlp-mono">#{r.judge_config_id}</td>
                <td>{r.labels_written}</td>
                <td>{money(r.dry_run ? r.estimated_cost_usd : r.cost_usd)}</td>
                <td className="mlp-muted">{stopReasonText(r.stopped_reason)}</td>
              </tr>
            ))}
          </Table>
        </Card>
      )}
    </div>
  );
}

// --- the config form --------------------------------------------------------

function JudgeForm({
  providers,
  busy,
  onCreate,
}: {
  providers: string[];
  busy: boolean;
  onCreate: (
    body: {
      name: string;
      provider: string;
      model_id: string;
      params: Record<string, unknown>;
      prompt_template: string | null;
      budget: Record<string, number> | null;
    },
    attach: boolean,
  ) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [provider, setProvider] = useState(providers[0] ?? "mock");
  const [modelId, setModelId] = useState("mock-1");
  const [baseUrl, setBaseUrl] = useState("");
  const [prompt, setPrompt] = useState("");
  const [projectUsd, setProjectUsd] = useState("");
  const [dailyUsd, setDailyUsd] = useState("");
  const [maxLabels, setMaxLabels] = useState("");

  const submit = () => {
    const params: Record<string, unknown> = {};
    if (baseUrl.trim()) params.base_url = baseUrl.trim();
    const budget: Record<string, number> = {};
    if (projectUsd.trim()) budget.project_usd = Number(projectUsd);
    if (dailyUsd.trim()) budget.daily_usd = Number(dailyUsd);
    if (maxLabels.trim()) budget.max_labels = Number(maxLabels);
    void onCreate(
      {
        name: name.trim(),
        provider,
        model_id: modelId.trim(),
        params,
        prompt_template: prompt.trim() || null,
        budget: Object.keys(budget).length ? budget : null,
      },
      true,
    );
  };

  return (
    <div className="mlp-stack" style={{ marginTop: 12 }} data-testid="judge-form">
      <label className="mlp-block-label">
        Name
        <input
          value={name}
          data-testid="judge-name"
          placeholder="claude-judge"
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label className="mlp-block-label">
        Provider
        <select
          value={provider}
          data-testid="judge-provider"
          onChange={(e) => setProvider(e.target.value)}
        >
          {providers.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>
      <p className="mlp-muted">{PROVIDER_BLURB[provider] ?? ""}</p>
      <label className="mlp-block-label">
        Model id
        <input
          value={modelId}
          data-testid="judge-model"
          onChange={(e) => setModelId(e.target.value)}
        />
      </label>
      {provider === "openai_compatible" && (
        <label className="mlp-block-label">
          Base URL
          <input
            value={baseUrl}
            data-testid="judge-base-url"
            placeholder="http://localhost:8000/v1"
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </label>
      )}
      <label className="mlp-block-label">
        Prompt preamble (versioned)
        <textarea
          rows={3}
          value={prompt}
          data-testid="judge-prompt"
          placeholder="Optional. Use {guidelines} and {task} to place them explicitly."
          onChange={(e) => setPrompt(e.target.value)}
        />
      </label>
      <div className="mlp-actions" style={{ flexWrap: "wrap" }}>
        <label className="mlp-inline-label">
          Cap $/project
          <input
            value={projectUsd}
            data-testid="judge-cap-project"
            onChange={(e) => setProjectUsd(e.target.value)}
            style={{ width: 90 }}
          />
        </label>
        <label className="mlp-inline-label">
          Cap $/day
          <input
            value={dailyUsd}
            data-testid="judge-cap-daily"
            onChange={(e) => setDailyUsd(e.target.value)}
            style={{ width: 90 }}
          />
        </label>
        <label className="mlp-inline-label">
          Max labels
          <input
            value={maxLabels}
            data-testid="judge-cap-labels"
            onChange={(e) => setMaxLabels(e.target.value)}
            style={{ width: 90 }}
          />
        </label>
      </div>
      <p className="mlp-muted">
        API keys are never stored here. The server reads them from an environment variable
        (<code>$ANTHROPIC_API_KEY</code>, <code>$OPENAI_API_KEY</code>), so a config stays
        shareable without leaking credentials.
      </p>
      <div className="mlp-actions">
        <button
          className="mlp-btn mlp-btn-primary"
          data-testid="judge-create"
          disabled={busy || !name.trim() || !modelId.trim()}
          onClick={submit}
        >
          Create &amp; enroll
        </button>
      </div>
    </div>
  );
}
