import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TaskClient } from "../api/client";
import type { Task, TemplateSchema } from "../api/types";
import { GALLERY, IMAGE_CLASSIFICATION, SIDE_BY_SIDE, SUMMARY_QUALITY, TEXT_SENTIMENT } from "../fixtures/gallery";
import { Annotate } from "./Annotate";

function makeTask(payload: Record<string, unknown>, variant?: Record<string, unknown>): Task {
  return { slot_id: 42, unit_id: 7, project_id: 1, payload, variant: variant ?? null };
}

function mockClient(task: Task): TaskClient & {
  submit: ReturnType<typeof vi.fn>;
  skip: ReturnType<typeof vi.fn>;
  nextTask: ReturnType<typeof vi.fn>;
} {
  return {
    nextTask: vi.fn().mockResolvedValueOnce(task).mockResolvedValue(null),
    submit: vi.fn().mockResolvedValue({
      id: 1,
      slot_id: task.slot_id,
      unit_id: task.unit_id,
      annotator_id: 1,
      value: {},
      is_valid: true,
    }),
    skip: vi.fn().mockResolvedValue({ slot_id: task.slot_id, status: "open" }),
  };
}

function renderAnnotate(schema: TemplateSchema, task: Task, guidelines = "# Do good work") {
  const client = mockClient(task);
  render(
    <Annotate client={client} annotatorId={1} projectId={1} schema={schema} guidelines={guidelines} />,
  );
  return client;
}

describe("Annotate — every gallery template renders end-to-end", () => {
  for (const entry of GALLERY) {
    it(`renders ${entry.schema.name}`, async () => {
      const variant =
        entry.schema.variants?.values?.length ?
          { [entry.schema.variants.dimension]: entry.schema.variants.values[0] }
        : undefined;
      renderAnnotate(entry.schema, makeTask(entry.payload, variant));
      // input rail with every declared input
      await screen.findByTestId("input-rail");
      for (const input of entry.schema.inputs) {
        expect(screen.getByTestId(`input-${input.id}`)).toBeInTheDocument();
      }
      // display region present (stack/split) or a columns grid (columns arrangement)
      const hasDisplay =
        screen.queryByTestId("display-region") ?? document.querySelector(".mlp-layout-columns");
      expect(hasDisplay).toBeTruthy();
    });
  }
});

describe("Annotate — keyboard-only submission (zero mouse events)", () => {
  it("side-by-side auto-submits on ArrowRight and canonicalizes under variant AB", async () => {
    const client = renderAnnotate(SIDE_BY_SIDE, makeTask(GALLERY[0].payload, { panel_order: "AB" }));
    await screen.findByTestId("input-choice");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(client.submit).toHaveBeenCalledTimes(1));
    expect(client.submit).toHaveBeenCalledWith(
      42,
      1,
      // objectContaining: the body also carries latency_ms (§6.2 speed flags),
      // which is a wall-clock value and not worth pinning here.
      expect.objectContaining({ raw: { choice: "Right" }, value: { choice: "B" } }),
    );
  });

  it("side-by-side canonicalizes Right→A under variant BA", async () => {
    const client = renderAnnotate(SIDE_BY_SIDE, makeTask(GALLERY[0].payload, { panel_order: "BA" }));
    await screen.findByTestId("input-choice");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(client.submit).toHaveBeenCalledTimes(1));
    expect(client.submit).toHaveBeenCalledWith(
      42,
      1,
      expect.objectContaining({ raw: { choice: "Right" }, value: { choice: "A" } }),
    );
  });

  it("image-classification auto-submits on digit key", async () => {
    const client = renderAnnotate(IMAGE_CLASSIFICATION, makeTask(GALLERY[1].payload));
    await screen.findByTestId("input-category");
    fireEvent.keyDown(window, { key: "1" });
    await waitFor(() => expect(client.submit).toHaveBeenCalledTimes(1));
    expect(client.submit).toHaveBeenCalledWith(
      42,
      1,
      expect.objectContaining({ raw: { category: "cat" }, value: { category: "cat" } }),
    );
  });

  it("multi-input template submits on Enter after keyboard selections", async () => {
    const client = renderAnnotate(SUMMARY_QUALITY, makeTask(GALLERY[3].payload));
    await screen.findByTestId("input-faithfulness");
    fireEvent.keyDown(window, { key: "1" }); // faithfulness = 1
    fireEvent.keyDown(window, { key: "a" }); // coverage = 1
    fireEvent.keyDown(window, { key: "h" }); // fluency = 1
    expect(client.submit).not.toHaveBeenCalled(); // no auto-submit with >1 input
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => expect(client.submit).toHaveBeenCalledTimes(1));
    expect(client.submit).toHaveBeenCalledWith(
      42,
      1,
      expect.objectContaining({
        raw: { faithfulness: 1, coverage: 1, fluency: 1 },
        value: { faithfulness: 1, coverage: 1, fluency: 1 },
      }),
    );
  });
});

describe("Annotate — reserved keys (§2.4)", () => {
  it("'s' skips the task", async () => {
    const client = renderAnnotate(TEXT_SENTIMENT, makeTask(GALLERY[2].payload));
    await screen.findByTestId("input-sentiment");
    fireEvent.keyDown(window, { key: "s" });
    await waitFor(() => expect(client.skip).toHaveBeenCalledWith(42, 1));
  });

  it("'d' toggles dark mode on the document root so the page background follows", async () => {
    renderAnnotate(TEXT_SENTIMENT, makeTask(GALLERY[2].payload));
    const root = await screen.findByTestId("annotate-root");
    expect(root).toHaveAttribute("data-theme", "light");
    await waitFor(() =>
      expect(document.documentElement).toHaveAttribute("data-theme", "light"),
    );
    fireEvent.keyDown(window, { key: "d" });
    await waitFor(() => expect(root).toHaveAttribute("data-theme", "dark"));
    // the themed CSS variables hang off <html>, not an inner div
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });

  it("'g' toggles the guidelines panel", async () => {
    renderAnnotate(TEXT_SENTIMENT, makeTask(GALLERY[2].payload));
    await screen.findByTestId("guidelines-body"); // expanded on first task
    fireEvent.keyDown(window, { key: "g" });
    await waitFor(() => expect(screen.queryByTestId("guidelines-body")).toBeNull());
  });

  it("'u' undoes the last selection", async () => {
    renderAnnotate(TEXT_SENTIMENT, makeTask(GALLERY[2].payload));
    await screen.findByTestId("input-sentiment");
    fireEvent.keyDown(window, { key: "1" }); // select positive
    await waitFor(() =>
      expect(screen.getByTestId("btn-submit")).not.toBeDisabled(),
    );
    fireEvent.keyDown(window, { key: "u" });
    await waitFor(() => expect(screen.getByTestId("btn-submit")).toBeDisabled());
  });
});

describe("Annotate — session progress (§11)", () => {
  it("advances the progress bar as labels are submitted", async () => {
    renderAnnotate(IMAGE_CLASSIFICATION, makeTask(GALLERY[1].payload));
    await screen.findByTestId("input-category");
    const bar = screen.getByTestId("session-progress");
    expect(bar).toHaveAttribute("aria-valuenow", "0");
    fireEvent.keyDown(window, { key: "1" }); // auto-submits
    await waitFor(() => expect(bar).toHaveAttribute("aria-valuenow", "1"));
  });
});

describe("Annotate — hotkey overlay shows correct key for every element (§2.4)", () => {
  it("side-by-side overlay badges the choice options with their arrow keys", async () => {
    renderAnnotate(SIDE_BY_SIDE, makeTask(GALLERY[0].payload, { panel_order: "AB" }));
    await screen.findByTestId("input-choice");
    fireEvent.keyDown(window, { key: "?" });
    const overlay = await screen.findByTestId("hotkey-overlay");
    expect(overlay.querySelector('kbd[data-hotkey="left"]')).toBeTruthy();
    expect(overlay.querySelector('kbd[data-hotkey="down"]')).toBeTruthy();
    expect(overlay.querySelector('kbd[data-hotkey="right"]')).toBeTruthy();
    // reserved actions listed too
    expect(overlay.querySelector('kbd[data-hotkey="s"]')).toBeTruthy();
    expect(overlay.querySelector('kbd[data-hotkey="enter"]')).toBeTruthy();
  });

  it("image-classification overlay badges digits and Other", async () => {
    renderAnnotate(IMAGE_CLASSIFICATION, makeTask(GALLERY[1].payload));
    await screen.findByTestId("input-category");
    fireEvent.keyDown(window, { key: "?" });
    const overlay = await screen.findByTestId("hotkey-overlay");
    for (const k of ["1", "2", "3", "o"]) {
      expect(overlay.querySelector(`kbd[data-hotkey="${k}"]`)).toBeTruthy();
    }
  });
});
