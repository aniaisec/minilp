// Judges tab (M7, §7.1/§11). The client is a stub, so these assert on what the
// panel *does with what the API said* — which is where the interesting claims
// live: that "unpriced" never renders as $0.00, that a dry run is presented as
// an estimate rather than a charge, and that a stopped-on-budget run says so in
// words rather than leaving "budget_labels" on screen.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  Costs,
  EnrolledJudge,
  JudgeConfig,
  JudgeRunResponse,
  JudgeRunRow,
  Webhook,
  WebhookDelivery,
} from "../../api/types";
import { JudgesPanel } from "./JudgesPanel";
import { WebhooksPanel } from "./WebhooksPanel";

function enrolled(over: Partial<EnrolledJudge> = {}): EnrolledJudge {
  return {
    judge_config_id: 1,
    annotator_id: 9,
    display_name: "claude-judge v1",
    provider: "anthropic",
    model_id: "claude-sonnet-4",
    prompt_version: 1,
    budget: { project_usd: 2 },
    priced: true,
    price_source: "table:claude-sonnet-4",
    spend: { cost_usd: 0.5, daily_usd: 0.5, tokens: 1200, labels: 6, cache_hits: 2 },
    ...over,
  };
}

function runReport(over: Partial<JudgeRunResponse> = {}): JudgeRunResponse {
  return {
    project_id: 1,
    dry_run: false,
    labels_written: 3,
    cost_usd: 0.12,
    estimated_cost_usd: null,
    runs: [
      {
        run_id: 1,
        project_id: 1,
        judge_config_id: 1,
        annotator_id: 9,
        dry_run: false,
        status: "completed",
        stopped_reason: "exhausted",
        slots_attempted: 3,
        labels_written: 3,
        cache_hits: 0,
        tokens_in: 900,
        tokens_out: 120,
        cost_usd: 0.12,
        estimated_cost_usd: null,
        errors: [],
        webhooks_fired: 0,
      },
    ],
    ...over,
  };
}

const COSTS: Costs = {
  project_id: 1,
  judges: [
    {
      annotator_id: 9,
      display_name: "claude-judge v1",
      judge_config_id: 1,
      provider: "anthropic",
      model_id: "claude-sonnet-4",
      prompt_version: 1,
      labels: 6,
      cost_usd: 0.5,
      tokens_in: 1000,
      tokens_out: 200,
      cache_hits: 2,
      cache_hit_rate: 0.3333,
      cost_per_label: 0.0833,
      avg_latency_ms: 812.4,
      budget: { project_usd: 2 },
    },
  ],
  totals: {
    labels: 10,
    judge_labels: 6,
    human_labels: 4,
    cost_usd: 0.5,
    tokens: 1200,
    cache_hits: 2,
    cache_hit_rate: 0.3333,
    cost_per_judge_label: 0.0833,
  },
};

function stubClient(over: Record<string, unknown> = {}) {
  return {
    listProjectJudges: vi.fn().mockResolvedValue({ project_id: 1, judges: [enrolled()] }),
    listJudges: vi.fn().mockResolvedValue([
      { id: 1, name: "claude-judge", provider: "anthropic", model_id: "claude-sonnet-4", prompt_version: 1 },
      { id: 2, name: "local-ft", provider: "openai_compatible", model_id: "local-ft-v2", prompt_version: 1 },
    ] as JudgeConfig[]),
    listJudgeRuns: vi.fn().mockResolvedValue([] as JudgeRunRow[]),
    getCosts: vi.fn().mockResolvedValue(COSTS),
    listProviders: vi
      .fn()
      .mockResolvedValue({ providers: ["mock", "anthropic", "openai", "openai_compatible"] }),
    runJudges: vi.fn().mockResolvedValue(runReport()),
    attachJudge: vi.fn().mockResolvedValue({ annotator_id: 11 }),
    detachJudge: vi.fn().mockResolvedValue({ project_id: 1 }),
    createJudge: vi.fn().mockResolvedValue({ id: 3, name: "new", provider: "mock", model_id: "m", prompt_version: 1 }),
    ...over,
  } as never;
}

function renderPanel(client = stubClient()) {
  render(<JudgesPanel client={client} projectId={1} />);
  return client;
}

// --- enrolled judges ---------------------------------------------------------

describe("JudgesPanel", () => {
  it("lists enrolled judges with spend and cap usage", async () => {
    renderPanel();
    const row = await screen.findByTestId("judge-row-1");
    expect(within(row).getByText("claude-judge v1")).toBeInTheDocument();
    expect(within(row).getByText("anthropic")).toBeInTheDocument();
    expect(within(row).getByText(/\$0\.5000/)).toBeInTheDocument();
    expect(within(row).getByText(/2 cached/)).toBeInTheDocument();
    expect(within(row).getByText(/project \$/)).toBeInTheDocument();
  });

  it("says 'unpriced' rather than $0.00 when no price is known", async () => {
    // A model with no published price must never render as free — that is how a
    // budget cap becomes a cap you do not actually have.
    renderPanel(
      stubClient({
        listProjectJudges: vi.fn().mockResolvedValue({
          project_id: 1,
          judges: [enrolled({ priced: false, price_source: "unknown" })],
        }),
      }),
    );
    const row = await screen.findByTestId("judge-row-1");
    expect(within(row).getByText("unpriced")).toBeInTheDocument();
    expect(within(row).queryByText(/\$0\.0000/)).not.toBeInTheDocument();
  });

  it("shows an empty state when nothing is enrolled and disables the run buttons", async () => {
    renderPanel(
      stubClient({
        listProjectJudges: vi.fn().mockResolvedValue({ project_id: 1, judges: [] }),
        getCosts: vi.fn().mockResolvedValue({ ...COSTS, judges: [] }),
      }),
    );
    expect(await screen.findByTestId("judges-empty")).toBeInTheDocument();
    expect(screen.getByTestId("judge-dry-run")).toBeDisabled();
    expect(screen.getByTestId("judge-run")).toBeDisabled();
  });

  it("marks 'uncapped' when a judge has no budget", async () => {
    renderPanel(
      stubClient({
        listProjectJudges: vi
          .fn()
          .mockResolvedValue({ project_id: 1, judges: [enrolled({ budget: null })] }),
      }),
    );
    const row = await screen.findByTestId("judge-row-1");
    expect(within(row).getByText("uncapped")).toBeInTheDocument();
  });

  // --- running -------------------------------------------------------------

  it("dry-runs with the chosen limit and labels the result an estimate", async () => {
    const client = renderPanel(
      stubClient({
        runJudges: vi.fn().mockResolvedValue(
          runReport({ dry_run: true, labels_written: 0, cost_usd: 0, estimated_cost_usd: 0.42 }),
        ),
      }),
    );
    await screen.findByTestId("judge-row-1");

    fireEvent.change(screen.getByTestId("judge-limit"), { target: { value: "7" } });
    fireEvent.click(screen.getByTestId("judge-dry-run"));

    await waitFor(() =>
      expect(client.runJudges).toHaveBeenCalledWith(1, {
        dry_run: true,
        limit: 7,
        judge_config_id: undefined,
      }),
    );
    const report = await screen.findByTestId("run-report");
    expect(within(report).getByText("Estimate")).toBeInTheDocument();
    expect(within(report).getByText(/\$0\.4200/)).toBeInTheDocument();
    expect(within(report).getByText("not charged")).toBeInTheDocument();
  });

  it("runs live and reports labels written", async () => {
    const client = renderPanel();
    await screen.findByTestId("judge-row-1");
    fireEvent.click(screen.getByTestId("judge-run"));

    await waitFor(() => expect(client.runJudges).toHaveBeenCalled());
    const report = await screen.findByTestId("run-report");
    expect(within(report).getByText("Run report")).toBeInTheDocument();
    expect(within(report).getByText(/no eligible slots left/)).toBeInTheDocument();
  });

  it("explains a budget stop in words, not in an enum value", async () => {
    const stopped = runReport({ labels_written: 2 });
    stopped.runs[0].stopped_reason = "budget_labels";
    stopped.runs[0].status = "stopped";
    stopped.runs[0].webhooks_fired = 1;

    renderPanel(stubClient({ runJudges: vi.fn().mockResolvedValue(stopped) }));
    await screen.findByTestId("judge-row-1");
    fireEvent.click(screen.getByTestId("judge-run"));

    const line = await screen.findByTestId("run-line-1");
    expect(line).toHaveTextContent("stopped — label cap reached");
    expect(line).toHaveTextContent("1 webhook(s) fired");
    expect(line).not.toHaveTextContent("budget_labels");
  });

  it("surfaces per-unit run errors without hiding them", async () => {
    const failed = runReport({ labels_written: 1 });
    failed.runs[0].errors = [
      { stage: "parse", unit_id: 12, error: "no JSON object found in response" },
    ];
    renderPanel(stubClient({ runJudges: vi.fn().mockResolvedValue(failed) }));
    await screen.findByTestId("judge-row-1");
    fireEvent.click(screen.getByTestId("judge-run"));

    expect(await screen.findByText("1 problem(s)")).toBeInTheDocument();
    expect(screen.getByText(/no JSON object found/)).toBeInTheDocument();
  });

  it("shows the API error instead of failing silently", async () => {
    renderPanel(
      stubClient({ runJudges: vi.fn().mockRejectedValue(new Error("no judges enrolled")) }),
    );
    await screen.findByTestId("judge-row-1");
    fireEvent.click(screen.getByTestId("judge-run"));
    expect(await screen.findByTestId("judges-error")).toHaveTextContent("no judges enrolled");
  });

  // --- costs ---------------------------------------------------------------

  it("renders the cost panel with $/label and cache-hit rate", async () => {
    renderPanel();
    const panel = await screen.findByTestId("costs-panel");
    // Once in the summary stat, once in the per-judge row.
    expect(within(panel).getAllByText("33%")).toHaveLength(2);
    expect(within(panel).getByText(/6 judge · 4 human/)).toBeInTheDocument();
    expect(within(panel).getByText("812 ms")).toBeInTheDocument();
  });

  // --- enrollment ----------------------------------------------------------

  it("offers unenrolled configs and attaches one on click", async () => {
    const client = renderPanel();
    const button = await screen.findByTestId("attach-2");
    expect(screen.queryByTestId("attach-1")).not.toBeInTheDocument(); // already enrolled
    fireEvent.click(button);
    await waitFor(() => expect(client.attachJudge).toHaveBeenCalledWith(1, 2));
  });

  it("detaches a judge", async () => {
    const client = renderPanel();
    fireEvent.click(await screen.findByTestId("detach-1"));
    await waitFor(() => expect(client.detachJudge).toHaveBeenCalledWith(1, 1));
  });

  it("creates a judge config and enrolls it in one step", async () => {
    const client = renderPanel();
    fireEvent.click(await screen.findByTestId("toggle-judge-form"));

    fireEvent.change(screen.getByTestId("judge-name"), { target: { value: "gpt-judge" } });
    fireEvent.change(screen.getByTestId("judge-provider"), { target: { value: "openai" } });
    fireEvent.change(screen.getByTestId("judge-model"), { target: { value: "gpt-4o-mini" } });
    fireEvent.change(screen.getByTestId("judge-cap-project"), { target: { value: "5" } });
    fireEvent.click(screen.getByTestId("judge-create"));

    await waitFor(() =>
      expect(client.createJudge).toHaveBeenCalledWith({
        name: "gpt-judge",
        provider: "openai",
        model_id: "gpt-4o-mini",
        params: {},
        prompt_template: null,
        budget: { project_usd: 5 },
      }),
    );
    await waitFor(() => expect(client.attachJudge).toHaveBeenCalledWith(1, 3));
  });

  it("asks for a base URL only for the local/compatible provider", async () => {
    renderPanel();
    fireEvent.click(await screen.findByTestId("toggle-judge-form"));
    expect(screen.queryByTestId("judge-base-url")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("judge-provider"), {
      target: { value: "openai_compatible" },
    });
    expect(screen.getByTestId("judge-base-url")).toBeInTheDocument();
  });

  it("never offers a field for an API key", async () => {
    // Keys live in server-side environment variables (§7.1) — a form field would
    // put them in the database and into any exported bundle.
    renderPanel();
    fireEvent.click(await screen.findByTestId("toggle-judge-form"));
    const form = screen.getByTestId("judge-form");
    expect(within(form).queryByPlaceholderText(/sk-/i)).not.toBeInTheDocument();
    expect(form.textContent).toMatch(/API keys are never stored here/);
  });

  it("requires a name and model before it will create", async () => {
    renderPanel();
    fireEvent.click(await screen.findByTestId("toggle-judge-form"));
    expect(screen.getByTestId("judge-create")).toBeDisabled();
    fireEvent.change(screen.getByTestId("judge-name"), { target: { value: "x" } });
    expect(screen.getByTestId("judge-create")).not.toBeDisabled();
  });

  // --- history -------------------------------------------------------------

  it("shows dry and live runs together in the history", async () => {
    const rows: JudgeRunRow[] = [
      {
        id: 2,
        project_id: 1,
        judge_config_id: 1,
        annotator_id: 9,
        dry_run: false,
        status: "completed",
        stopped_reason: "exhausted",
        slots_attempted: 4,
        labels_written: 4,
        cache_hits: 1,
        tokens_in: 10,
        tokens_out: 5,
        cost_usd: 0.2,
        estimated_cost_usd: null,
        errors: null,
        started_at: "2026-07-28T10:00:00Z",
        finished_at: "2026-07-28T10:00:05Z",
      },
      {
        id: 1,
        project_id: 1,
        judge_config_id: 1,
        annotator_id: 9,
        dry_run: true,
        status: "completed",
        stopped_reason: "exhausted",
        slots_attempted: 4,
        labels_written: 0,
        cache_hits: 0,
        tokens_in: 10,
        tokens_out: 5,
        cost_usd: 0,
        estimated_cost_usd: 0.19,
        errors: null,
        started_at: "2026-07-28T09:59:00Z",
        finished_at: "2026-07-28T09:59:01Z",
      },
    ];
    renderPanel(stubClient({ listJudgeRuns: vi.fn().mockResolvedValue(rows) }));
    const history = await screen.findByTestId("run-history");
    expect(within(history).getByText("live")).toBeInTheDocument();
    expect(within(history).getByText("estimate")).toBeInTheDocument();
    expect(within(history).getByText(/\$0\.1900/)).toBeInTheDocument();
  });
});

// --- webhooks ---------------------------------------------------------------

function webhookClient(over: Record<string, unknown> = {}) {
  return {
    listWebhooks: vi.fn().mockResolvedValue([
      {
        id: 1,
        event: "budget.cap_reached",
        target_url: "https://hooks.test/mlp",
        project_id: 1,
        status: "active",
        has_secret: true,
      },
    ] as Webhook[]),
    listDeliveries: vi.fn().mockResolvedValue([] as WebhookDelivery[]),
    createWebhook: vi.fn().mockResolvedValue({}),
    deleteWebhook: vi.fn().mockResolvedValue({ deleted: 1 }),
    ...over,
  } as never;
}

describe("WebhooksPanel", () => {
  it("lists this project's hooks and instance-wide ones", async () => {
    render(<WebhooksPanel client={webhookClient()} projectId={1} />);
    const row = await screen.findByTestId("webhook-row-1");
    expect(within(row).getByText("budget.cap_reached")).toBeInTheDocument();
    expect(within(row).getByText("this project")).toBeInTheDocument();
  });

  it("hides another project's hooks", async () => {
    render(
      <WebhooksPanel
        client={webhookClient({
          listWebhooks: vi.fn().mockResolvedValue([
            {
              id: 5,
              event: "project.completed",
              target_url: "https://x.test/h",
              project_id: 99,
              status: "active",
              has_secret: false,
            },
          ]),
        })}
        projectId={1}
      />,
    );
    expect(await screen.findByTestId("webhooks-empty")).toBeInTheDocument();
  });

  it("registers a project-scoped webhook with a secret", async () => {
    const client = webhookClient();
    render(<WebhooksPanel client={client} projectId={1} />);
    await screen.findByTestId("webhook-row-1");

    fireEvent.change(screen.getByTestId("webhook-event"), {
      target: { value: "gold.accuracy_dropped" },
    });
    fireEvent.change(screen.getByTestId("webhook-url"), {
      target: { value: "https://hooks.test/gold" },
    });
    fireEvent.change(screen.getByTestId("webhook-secret"), { target: { value: "shh" } });
    fireEvent.click(screen.getByTestId("webhook-create"));

    await waitFor(() =>
      expect(client.createWebhook).toHaveBeenCalledWith({
        event: "gold.accuracy_dropped",
        target_url: "https://hooks.test/gold",
        secret: "shh",
        project_id: 1,
      }),
    );
  });

  it("registers an instance-wide hook when the scope box is cleared", async () => {
    const client = webhookClient();
    render(<WebhooksPanel client={client} projectId={1} />);
    await screen.findByTestId("webhook-row-1");
    fireEvent.change(screen.getByTestId("webhook-url"), {
      target: { value: "https://hooks.test/all" },
    });
    fireEvent.click(screen.getByTestId("webhook-scoped"));
    fireEvent.click(screen.getByTestId("webhook-create"));

    await waitFor(() =>
      expect(client.createWebhook).toHaveBeenCalledWith(
        expect.objectContaining({ project_id: null }),
      ),
    );
  });

  it("will not register without a URL", async () => {
    render(<WebhooksPanel client={webhookClient()} projectId={1} />);
    expect(await screen.findByTestId("webhook-create")).toBeDisabled();
  });

  it("flags a failed delivery rather than letting it look quiet", async () => {
    render(
      <WebhooksPanel
        client={webhookClient({
          listDeliveries: vi.fn().mockResolvedValue([
            {
              id: 3,
              webhook_id: 1,
              event: "budget.cap_reached",
              project_id: 1,
              payload: {},
              status: "failed",
              attempts: 3,
              status_code: null,
              error: "connection refused",
              created_at: "2026-07-28T10:00:00Z",
            },
          ]),
        })}
        projectId={1}
      />,
    );
    const row = await screen.findByTestId("delivery-3");
    expect(within(row).getByText("failed")).toHaveClass("mlp-status-failed");
    expect(screen.getByTestId("deliveries-warning")).toBeInTheDocument();
  });

  it("removes a webhook", async () => {
    const client = webhookClient();
    render(<WebhooksPanel client={client} projectId={1} />);
    fireEvent.click(await screen.findByTestId("delete-webhook-1"));
    await waitFor(() => expect(client.deleteWebhook).toHaveBeenCalledWith(1));
  });
});
