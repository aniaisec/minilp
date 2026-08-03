// Export panel (§10, M6) + the M10 marketplace bundle section it grew. The
// JSONL half already has integration coverage through the manual test script;
// these tests focus on what's new — downloading a project's config as a bundle.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MarketplaceBundle } from "../../api/types";
import { ExportPanel } from "./ExportPanel";

function stubClient(over: Record<string, unknown> = {}) {
  return {
    fetchExport: vi.fn().mockResolvedValue('{"a": 1}\n'),
    exportProjectBundle: vi.fn().mockResolvedValue({
      bundle_version: 1,
      kind: "project",
      name: "demo",
      exported_at: "2026-01-01T00:00:00Z",
      template: { name: "demo", inputs: [] },
      judge_configs: [],
      project: { labels_per_unit: 1 },
    } as MarketplaceBundle),
    ...over,
  } as never;
}

beforeEach(() => {
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:mock"),
    revokeObjectURL: vi.fn(),
  });
});

describe("ExportPanel bundle section", () => {
  it("downloads a project bundle via exportProjectBundle", async () => {
    const client = stubClient();
    render(<ExportPanel client={client} projectId={6} />);

    fireEvent.click(screen.getByTestId("bundle-export-download"));

    await waitFor(() => expect(client.exportProjectBundle).toHaveBeenCalledWith(6));
    expect(screen.queryByTestId("bundle-export-error")).not.toBeInTheDocument();
  });

  it("shows an error if the bundle export fails", async () => {
    const client = stubClient({
      exportProjectBundle: vi.fn().mockRejectedValue(new Error("project 6 not found")),
    });
    render(<ExportPanel client={client} projectId={6} />);

    fireEvent.click(screen.getByTestId("bundle-export-download"));

    const err = await screen.findByTestId("bundle-export-error");
    expect(err.textContent).toContain("project 6 not found");
  });
});
