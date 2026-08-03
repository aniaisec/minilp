// Marketplace panel (M10, §12). The client is a stub — these assert on what the
// panel does with what the API says: local bundles list and import, a pasted
// bundle imports (or shows a parse error first), and export buttons call the
// right per-resource endpoint and trigger a download.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { JudgeConfig, LocalBundleInfo, MarketplaceBundle, Template } from "../../api/types";
import { MarketplacePanel } from "./MarketplacePanel";

const LOCAL_BUNDLES: LocalBundleInfo[] = [
  {
    filename: "toxicity-triage.json",
    kind: "project",
    name: "Toxicity triage (starter kit)",
    description: "A ready-to-run project.",
    bundle_version: 1,
  },
  {
    filename: "summarization-quality.json",
    kind: "template",
    name: "summarization-quality",
    description: "Rate a summary.",
    bundle_version: 1,
  },
];

const TEMPLATES: Template[] = [
  { id: 1, name: "side-by-side-preference", version: 1, kind: "builtin", schema: { name: "x", inputs: [] } },
];

const JUDGES: JudgeConfig[] = [
  { id: 5, name: "claude-judge", provider: "anthropic", model_id: "claude-x", prompt_version: 2 },
];

function stubClient(over: Record<string, unknown> = {}) {
  return {
    listLocalBundles: vi.fn().mockResolvedValue({ bundles: LOCAL_BUNDLES }),
    listTemplates: vi.fn().mockResolvedValue(TEMPLATES),
    listJudges: vi.fn().mockResolvedValue(JUDGES),
    getLocalBundle: vi.fn().mockResolvedValue({
      bundle_version: 1,
      kind: "template",
      name: "summarization-quality",
      exported_at: "2026-01-01T00:00:00Z",
      template: { name: "summarization-quality", inputs: [] },
    } as MarketplaceBundle),
    importLocalBundle: vi.fn().mockResolvedValue({
      kind: "project",
      template: { id: 9, name: "toxicity-triage", version: 1 },
      judge_configs: [{ id: 10, name: "toxicity-judge", prompt_version: 1 }],
      project: { id: 3, name: "Toxicity triage (starter kit)" },
    }),
    importBundle: vi.fn().mockResolvedValue({
      kind: "template",
      template: { id: 11, name: "imported", version: 1 },
    }),
    exportTemplateBundle: vi.fn().mockResolvedValue({
      bundle_version: 1,
      kind: "template",
      name: "side-by-side-preference",
      exported_at: "2026-01-01T00:00:00Z",
      template: { name: "side-by-side-preference", inputs: [] },
    } as MarketplaceBundle),
    exportJudgeBundle: vi.fn().mockResolvedValue({
      bundle_version: 1,
      kind: "judge_config",
      name: "claude-judge",
      exported_at: "2026-01-01T00:00:00Z",
      judge_config: { name: "claude-judge", provider: "anthropic", model_id: "claude-x" },
    } as MarketplaceBundle),
    ...over,
  } as never;
}

function renderPanel(client = stubClient()) {
  render(<MarketplacePanel client={client} />);
  return client;
}

beforeEach(() => {
  // jsdom does not implement the Blob URL APIs the download buttons use.
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:mock"),
    revokeObjectURL: vi.fn(),
  });
});

describe("MarketplacePanel", () => {
  it("lists the shipped local bundles with their kind", async () => {
    renderPanel();
    const row = await screen.findByTestId("local-bundle-toxicity-triage.json");
    expect(within(row).getByText("Toxicity triage (starter kit)")).toBeInTheDocument();
    expect(within(row).getByText("project")).toBeInTheDocument();
    expect(await screen.findByTestId("local-bundle-summarization-quality.json")).toBeInTheDocument();
  });

  it("imports a shipped bundle by filename and reports what was created", async () => {
    const client = renderPanel();
    await screen.findByTestId("local-bundle-toxicity-triage.json");

    fireEvent.click(screen.getByTestId("local-bundle-import-toxicity-triage.json"));

    await waitFor(() =>
      expect(client.importLocalBundle).toHaveBeenCalledWith("toxicity-triage.json", true),
    );
    const result = await screen.findByTestId("marketplace-result");
    expect(result.textContent).toContain("toxicity-triage");
    expect(result.textContent).toContain("Toxicity triage (starter kit)");
  });

  it("respects the 'also create the project' checkbox", async () => {
    const client = renderPanel();
    await screen.findByTestId("local-bundle-toxicity-triage.json");

    fireEvent.click(screen.getByTestId("marketplace-create-project"));
    fireEvent.click(screen.getByTestId("local-bundle-import-toxicity-triage.json"));

    await waitFor(() =>
      expect(client.importLocalBundle).toHaveBeenCalledWith("toxicity-triage.json", false),
    );
  });

  it("loads a local bundle's full JSON into the paste box on 'View'", async () => {
    const client = renderPanel();
    await screen.findByTestId("local-bundle-summarization-quality.json");
    fireEvent.click(screen.getByTestId("local-bundle-view-summarization-quality.json"));

    await waitFor(() => expect(client.getLocalBundle).toHaveBeenCalledWith("summarization-quality.json"));
    const box = (await screen.findByTestId("marketplace-paste")) as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toContain("summarization-quality"));
  });

  it("shows a JSON parse error instead of importing garbage", async () => {
    const client = renderPanel();
    fireEvent.change(screen.getByTestId("marketplace-paste"), { target: { value: "{not json" } });
    fireEvent.click(screen.getByTestId("marketplace-import"));

    expect(await screen.findByTestId("marketplace-parse-error")).toBeInTheDocument();
    expect(client.importBundle).not.toHaveBeenCalled();
  });

  it("imports a well-formed pasted bundle", async () => {
    const client = renderPanel();
    const bundle = { bundle_version: 1, kind: "template", template: { name: "x", inputs: [] } };
    fireEvent.change(screen.getByTestId("marketplace-paste"), {
      target: { value: JSON.stringify(bundle) },
    });
    fireEvent.click(screen.getByTestId("marketplace-import"));

    await waitFor(() => expect(client.importBundle).toHaveBeenCalledWith(bundle, true));
    expect(await screen.findByTestId("marketplace-result")).toBeInTheDocument();
  });

  it("surfaces an import error from the API", async () => {
    const client = stubClient({
      importBundle: vi.fn().mockRejectedValue(new Error("unknown provider 'vibes'")),
    });
    renderPanel(client);
    fireEvent.change(screen.getByTestId("marketplace-paste"), {
      target: { value: '{"bundle_version":1,"kind":"judge_config"}' },
    });
    fireEvent.click(screen.getByTestId("marketplace-import"));

    const err = await screen.findByTestId("marketplace-error");
    expect(err.textContent).toContain("unknown provider");
  });

  it("lists templates and judge configs with a per-row export button", async () => {
    const client = renderPanel();
    await screen.findByTestId("export-template-1");
    expect(await screen.findByTestId("export-judge-5")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("export-template-download-1"));
    await waitFor(() => expect(client.exportTemplateBundle).toHaveBeenCalledWith(1));

    fireEvent.click(screen.getByTestId("export-judge-download-5"));
    await waitFor(() => expect(client.exportJudgeBundle).toHaveBeenCalledWith(5));
  });

  it("shows an empty state when there are no judge configs yet", async () => {
    renderPanel(stubClient({ listJudges: vi.fn().mockResolvedValue([]) }));
    expect(await screen.findByTestId("export-judges-empty")).toBeInTheDocument();
  });
});
