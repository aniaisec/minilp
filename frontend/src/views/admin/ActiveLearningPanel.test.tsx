// Active-learning tab (M9, §8). Stub client, same discipline as
// JudgesPanel.test.tsx: assert on what the panel does with what the API said.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ActiveLearningBatch, EnrolledJudge, IterationCurve } from "../../api/types";
import { ActiveLearningPanel } from "./ActiveLearningPanel";

function judge(over: Partial<EnrolledJudge> = {}): EnrolledJudge {
  return {
    judge_config_id: 1,
    annotator_id: 9,
    display_name: "local-ft v2",
    provider: "mock",
    model_id: "ckpt-2",
    prompt_version: 2,
    budget: null,
    priced: true,
    price_source: "table:mock",
    spend: { cost_usd: 0, daily_usd: 0, tokens: 100, labels: 6, cache_hits: 0 },
    ...over,
  };
}

function curve(over: Partial<IterationCurve> = {}): IterationCurve {
  return {
    project_id: 1,
    name: "local-ft",
    human_minutes: 12.5,
    iterations: [
      {
        judge_config_id: 1,
        iteration: 1,
        provider: "mock",
        model_id: "ckpt-1",
        annotator_id: 8,
        enrolled: true,
        gold_accuracy: { passes: 1, total: 6, rate: 0.1667 },
        agreement_vs_final: { agreements: 2, comparisons: 6, rate: 0.3333 },
        spend: { cost_usd: 0, tokens: 80, labels: 6 },
        label_count: 6,
        created_at: "2026-07-28T09:00:00Z",
      },
      {
        judge_config_id: 2,
        iteration: 2,
        provider: "mock",
        model_id: "ckpt-2",
        annotator_id: 9,
        enrolled: true,
        gold_accuracy: { passes: 3, total: 6, rate: 0.5 },
        agreement_vs_final: { agreements: 4, comparisons: 6, rate: 0.6667 },
        spend: { cost_usd: 0, tokens: 90, labels: 6 },
        label_count: 6,
        created_at: "2026-07-28T09:05:00Z",
      },
    ],
    ...over,
  };
}

function batchResult(over: Partial<ActiveLearningBatch> = {}): ActiveLearningBatch {
  return {
    project_id: 1,
    judge_config_id: 2,
    pool_size: 2,
    dropped_by_dedupe: 0,
    units: [
      { unit_id: 5, priority: 0, disagreement: 0.5, entropy: 1.0, confidence: 0.2, score: 0.77 },
      { unit_id: 7, priority: 0, disagreement: null, entropy: null, confidence: null, score: 0.5 },
    ],
    ...over,
  };
}

function stubClient(over: Record<string, unknown> = {}) {
  return {
    listProjectJudges: vi.fn().mockResolvedValue({ project_id: 1, judges: [judge()] }),
    iterationCurve: vi.fn().mockResolvedValue(curve()),
    activeLearningBatch: vi.fn().mockResolvedValue(batchResult()),
    registerCheckpoint: vi.fn().mockResolvedValue({
      project_id: 1,
      judge_config_id: 3,
      name: "local-ft",
      iteration: 3,
      provider: "mock",
      model_id: "ckpt-3",
      annotator_id: 10,
    }),
    ...over,
  } as never;
}

function renderPanel(client = stubClient()) {
  render(<ActiveLearningPanel client={client} projectId={1} />);
  return client;
}

describe("ActiveLearningPanel", () => {
  it("shows the empty state when no checkpoint has been registered", async () => {
    renderPanel(
      stubClient({ listProjectJudges: vi.fn().mockResolvedValue({ project_id: 1, judges: [] }) }),
    );
    expect(await screen.findByTestId("al-no-checkpoints")).toBeInTheDocument();
  });

  it("derives the checkpoint line from enrolled judges and loads its curve", async () => {
    const client = renderPanel();
    await waitFor(() => expect(client.iterationCurve).toHaveBeenCalledWith(1, "local-ft"));
    const table = await screen.findByTestId("al-iterations-table");
    expect(within(table).getByText("v1")).toBeInTheDocument();
    expect(within(table).getByText("v2")).toBeInTheDocument();
  });

  it("renders gold accuracy climbing across iterations with raw counts", async () => {
    renderPanel();
    const row1 = await screen.findByTestId("al-iter-1");
    expect(within(row1).getByText(/17%/)).toBeInTheDocument();
    expect(within(row1).getByText(/\(1\/6\)/)).toBeInTheDocument();
    const row2 = await screen.findByTestId("al-iter-2");
    expect(within(row2).getByText(/50%/)).toBeInTheDocument();
  });

  it("surfaces human minutes alongside the curve", async () => {
    renderPanel();
    await screen.findByTestId("al-iterations-table");
    expect(screen.getByText("12.5")).toBeInTheDocument();
  });

  it("ranks the next batch, weighting in the latest checkpoint's confidence", async () => {
    const client = renderPanel();
    await screen.findByTestId("al-iterations-table");
    fireEvent.click(screen.getByTestId("al-load-batch"));

    await waitFor(() =>
      expect(client.activeLearningBatch).toHaveBeenCalledWith(1, {
        limit: 20,
        judgeConfigId: 2, // the latest iteration's judge_config_id
      }),
    );
    const table = await screen.findByTestId("al-batch-table");
    expect(within(table).getByText("#5")).toBeInTheDocument();
    expect(within(table).getByText("0.77")).toBeInTheDocument();
  });

  it("shows a neutral-score row's missing signals as em-dashes, not zeros", async () => {
    renderPanel();
    await screen.findByTestId("al-iterations-table");
    fireEvent.click(screen.getByTestId("al-load-batch"));
    const table = await screen.findByTestId("al-batch-table");
    const row = within(table).getByText("#7").closest("tr")!;
    expect(within(row).getAllByText("—")).toHaveLength(3);
  });

  it("says nothing is left to rank once the pool is empty", async () => {
    renderPanel(
      stubClient({
        activeLearningBatch: vi
          .fn()
          .mockResolvedValue(batchResult({ pool_size: 0, units: [] })),
      }),
    );
    await screen.findByTestId("al-iterations-table");
    fireEvent.click(screen.getByTestId("al-load-batch"));
    expect(await screen.findByTestId("al-batch-empty")).toBeInTheDocument();
  });

  it("registers a checkpoint and reloads the curve under its name", async () => {
    const client = renderPanel();
    await screen.findByTestId("al-iterations-table");
    fireEvent.click(screen.getByTestId("al-toggle-form"));

    fireEvent.change(screen.getByTestId("al-ckpt-name"), { target: { value: "local-ft" } });
    fireEvent.change(screen.getByTestId("al-ckpt-model"), { target: { value: "ckpt-3" } });
    fireEvent.click(screen.getByTestId("al-ckpt-submit"));

    await waitFor(() =>
      expect(client.registerCheckpoint).toHaveBeenCalledWith(1, {
        name: "local-ft",
        provider: "mock",
        model_id: "ckpt-3",
        params: null,
        budget: null,
      }),
    );
    await waitFor(() => expect(client.iterationCurve).toHaveBeenCalledTimes(2));
  });

  it("asks for a base URL only for the openai_compatible provider", async () => {
    renderPanel();
    await screen.findByTestId("al-iterations-table");
    fireEvent.click(screen.getByTestId("al-toggle-form"));
    expect(screen.queryByTestId("al-ckpt-base-url")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("al-ckpt-provider"), {
      target: { value: "openai_compatible" },
    });
    expect(screen.getByTestId("al-ckpt-base-url")).toBeInTheDocument();
  });

  it("requires a name and model before it will register", async () => {
    renderPanel(
      stubClient({ listProjectJudges: vi.fn().mockResolvedValue({ project_id: 1, judges: [] }) }),
    );
    fireEvent.click(await screen.findByTestId("al-toggle-form"));
    const submit = screen.getByTestId("al-ckpt-submit");
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByTestId("al-ckpt-model"), { target: { value: "m" } });
    expect(submit).not.toBeDisabled();
  });

  it("shows the API error instead of failing silently", async () => {
    renderPanel(
      stubClient({ iterationCurve: vi.fn().mockRejectedValue(new Error("project not found")) }),
    );
    expect(await screen.findByTestId("al-error")).toHaveTextContent("project not found");
  });
});
