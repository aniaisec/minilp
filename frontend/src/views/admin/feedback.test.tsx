// Phase 7 — the panels actually say something now.
//
// `Toast.test.tsx` proves the primitive works. This file proves the wiring:
// that the four operations the plan names ("exports, judge runs, template saves
// and webhook tests all complete with no confirmation today") now confirm
// themselves, and that they do it in the right register — success politely,
// failure pinned.
//
// Each panel is rendered inside a `ToastProvider`, which is how the app mounts
// it (one provider, above the surface switch in App.tsx).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../components/Toast";
import { IMAGE_CLASSIFICATION } from "../../fixtures/gallery";
import { ExportPanel } from "./ExportPanel";
import { JudgesPanel } from "./JudgesPanel";
import { TemplateEditor } from "./builder/TemplateEditor";
import { WebhooksPanel } from "./WebhooksPanel";

function withToasts(ui: React.ReactNode) {
  return render(<ToastProvider>{ui}</ToastProvider>);
}

// jsdom has no object URLs and no real downloads; the export path only needs
// them not to throw.
beforeEach(() => {
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:x"),
    revokeObjectURL: vi.fn(),
  });
  Object.defineProperty(HTMLAnchorElement.prototype, "click", {
    configurable: true,
    value: vi.fn(),
  });
});

describe("Export", () => {
  it("confirms a download that otherwise leaves nothing on the page", async () => {
    const client = {
      fetchExport: vi.fn().mockResolvedValue('{"a":1}\n{"a":2}\n'),
      exportProjectBundle: vi.fn(),
    } as never;
    withToasts(<ExportPanel client={client} projectId={3} />);

    fireEvent.click(screen.getByTestId("export-download"));

    const toast = await screen.findByTestId("toast");
    // The row count is the part that matters: an export of 0 rows downloads
    // perfectly well and is not what anyone meant to do.
    expect(toast).toHaveTextContent("Exported 2 rows.");
    expect(toast).toHaveTextContent("project-3-labels.jsonl");
    expect(screen.getByTestId("toast-polite")).toContainElement(toast);
  });

  it("reports a failed export inline, and does not also toast it", async () => {
    // One channel per failure. `ErrorState` already carries `role="alert"`, so
    // a toast beside it would announce the same sentence twice — and the
    // inline state is the better of the two, being anchored to the control
    // that failed.
    const client = {
      fetchExport: vi.fn().mockRejectedValue(new Error("502 from the API")),
      exportProjectBundle: vi.fn(),
    } as never;
    withToasts(<ExportPanel client={client} projectId={3} />);

    fireEvent.click(screen.getByTestId("export-download"));

    expect(await screen.findByTestId("export-error")).toHaveTextContent("502 from the API");
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
  });

  it("calls out a zero-row export instead of congratulating it", async () => {
    // An export of nothing downloads perfectly well and is never what anyone
    // meant, so it is not dressed up as a success.
    const client = {
      fetchExport: vi.fn().mockResolvedValue(""),
      exportProjectBundle: vi.fn(),
    } as never;
    withToasts(<ExportPanel client={client} projectId={3} />);

    fireEvent.click(screen.getByTestId("export-download"));

    const toast = await screen.findByTestId("toast");
    expect(toast).toHaveTextContent("Exported 0 rows.");
    expect(toast).toHaveTextContent("nothing to put in it");
  });
});

describe("Judge runs", () => {
  // The run controls are disabled with nothing enrolled, so there has to be one.
  const enrolled = {
    judge_config_id: 1,
    annotator_id: 2,
    display_name: "gpt-judge",
    provider: "mock",
    model_id: "mock-1",
    prompt_version: 1,
    budget: null,
    priced: true,
    price_source: "table",
    spend: null,
  };

  const base = {
    listProjectJudges: vi.fn().mockResolvedValue({ judges: [enrolled] }),
    listJudges: vi.fn().mockResolvedValue([]),
    listJudgeRuns: vi.fn().mockResolvedValue([]),
    getCosts: vi.fn().mockResolvedValue(null),
    listProviders: vi.fn().mockResolvedValue({ providers: ["mock"] }),
  };

  function runResponse(over: Record<string, unknown> = {}) {
    return {
      runs: [
        {
          run_id: 1,
          project_id: 1,
          judge_config_id: 1,
          annotator_id: 1,
          dry_run: false,
          // A *healthy* run: the backend always sets a `stopped_reason`, and
          // "limit" means "did the slots it was asked for". Keying the failure
          // toast off the reason rather than the status made every successful
          // run announce itself as a failure.
          status: "ok",
          stopped_reason: "limit",
          slots_attempted: 10,
          labels_written: 10,
          cache_hits: 0,
          tokens_in: 100,
          tokens_out: 50,
          cost_usd: 0.25,
          estimated_cost_usd: null,
          errors: [],
        },
      ],
      labels_written: 10,
      cost_usd: 0.25,
      estimated_cost_usd: null,
      ...over,
    };
  }

  it("does not cry failure over a run that simply finished", async () => {
    const client = {
      ...base,
      runJudges: vi.fn().mockResolvedValue(runResponse()),
    } as never;
    withToasts(<JudgesPanel client={client} projectId={1} />);

    fireEvent.click(await screen.findByTestId("judge-run"));

    const toast = await screen.findByTestId("toast");
    expect(toast).toHaveTextContent("Judge run finished — 10 labels written.");
    expect(screen.getByTestId("toast-polite")).toContainElement(toast);
  });

  it("treats a run that stopped at its cap as a failure, and pins it", async () => {
    // Not an HTTP error — the request succeeded and the labels written are
    // real. It is a failure in the only sense that matters: the work asked for
    // did not all happen, and finding that out at invoice time is the outcome
    // §7.3 exists to prevent.
    const client = {
      ...base,
      runJudges: vi.fn().mockResolvedValue(
        runResponse({
          runs: [
            {
              ...runResponse().runs[0],
              status: "stopped",
              stopped_reason: "budget_project",
              labels_written: 4,
            },
          ],
          labels_written: 4,
        }),
      ),
    } as never;
    withToasts(<JudgesPanel client={client} projectId={1} />);

    fireEvent.click(await screen.findByTestId("judge-run"));

    const toast = await screen.findByTestId("toast");
    expect(toast).toHaveTextContent("Judge run stopped early — 4 labels written.");
    expect(toast).toHaveTextContent(/budget cap/i);
    expect(screen.getByTestId("toast-assertive")).toContainElement(toast);
  });
});

describe("Webhooks", () => {
  it("confirms a registration whose only visible effect is a cleared form", async () => {
    const client = {
      listWebhooks: vi.fn().mockResolvedValue([]),
      listDeliveries: vi.fn().mockResolvedValue([]),
      createWebhook: vi.fn().mockResolvedValue({}),
    } as never;
    withToasts(<WebhooksPanel client={client} projectId={1} />);

    fireEvent.change(await screen.findByTestId("webhook-url"), {
      target: { value: "https://hooks.example.com/minilp" },
    });
    fireEvent.click(screen.getByTestId("webhook-create"));

    expect(await screen.findByTestId("toast")).toHaveTextContent("Webhook registered.");
  });
});

describe("Template saves", () => {
  it("reports the versioning outcome even though saving navigates away", async () => {
    // This is the case that makes the argument for toasts by itself. The note
    // this replaces rendered into a component that `onSaved` unmounted in the
    // same commit, so nobody had ever read it. The region lives above the
    // router, so the message survives.
    const existing = {
      id: 7,
      name: "my-template",
      version: 2,
      kind: "custom",
      description: "",
      // A real schema, because the builder refuses to save an invalid one and
      // an empty template is invalid.
      schema: IMAGE_CLASSIFICATION,
    };
    const client = {
      getTemplate: vi.fn().mockResolvedValue(existing),
      updateTemplate: vi.fn().mockResolvedValue({ ...existing, version: 3 }),
    } as never;
    const onSaved = vi.fn();

    withToasts(<TemplateEditor client={client} templateId={7} onSaved={onSaved} />);
    fireEvent.click(await screen.findByTestId("builder-save"));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const toast = await screen.findByTestId("toast");
    expect(toast).toHaveTextContent("Saved as a new version, v3.");
    expect(toast).toHaveTextContent("§2.5");
  });
});
