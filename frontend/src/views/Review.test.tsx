// M8 acceptance — the human review queue UI (§7.2, §12).
//
// Two claims the design rests on, tested here:
//
// 1. **Everything needed to decide is on the screen.** Per-judge votes, their
//    weights, their variants and their reasoning traces — §7.2 asks for all of
//    it, and a reviewer who has to leave the page to see why the ensemble
//    proposed something will stop looking.
// 2. **One key press per decision.** `a` approves, `o` opens the override, `n`
//    and `p` walk the queue, and deciding advances — the same throughput logic
//    the annotation view is built on.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MiniLpClient } from "../api/client";
import type { ReviewItem } from "../api/types";
import { IMAGE_CLASSIFICATION } from "../fixtures/gallery";
import { Review } from "./Review";

function item(over: Partial<ReviewItem> = {}): ReviewItem {
  return {
    unit_id: 11,
    project_id: 1,
    project_name: "Images",
    batch_id: null,
    priority: 0,
    is_gold: false,
    status: "labeled",
    escalated_at: "2026-07-29T10:00:00Z",
    escalation_reason: "max_labels_per_unit reached without consensus",
    failed_keys: ["category"],
    payload: { image_url: "http://x/1.png" },
    proposal: {
      unit_id: 11,
      method: "calibration_weighted",
      value: { category: "cat" },
      confidence: 0.62,
      entropy: 1.0,
      keys: {
        category: {
          winner: "cat",
          weight: 0.9,
          total_weight: 1.45,
          share: 0.62,
          support: 1,
          votes: 2,
          entropy: 1.0,
          candidates: [],
        },
      },
      votes: [
        {
          label_id: 1,
          annotator_id: 101,
          kind: "model",
          name: "claude-judge v1",
          judge: "claude-judge",
          reputation: 0.9,
          weight: 0.9,
          variant: null,
          value: { category: "cat" },
          raw: { category: "cat" },
          confidence: 0.81,
          reasoning: "The animal has retractable claws and vertical pupils.",
          cost_usd: 0.0002,
        },
        {
          label_id: 2,
          annotator_id: 102,
          kind: "human",
          name: "sam",
          judge: null,
          reputation: 0.55,
          weight: 0.55,
          variant: null,
          value: { category: "dog" },
          raw: { category: "dog" },
          confidence: null,
          reasoning: null,
          cost_usd: null,
        },
      ],
    },
    consensus_snapshot: {},
    ...over,
  };
}

function detailOf(base: ReviewItem): ReviewItem {
  return {
    ...base,
    template: { id: 3, name: "image-classification", version: 1, schema: IMAGE_CLASSIFICATION },
    guidelines_md: "",
    final_label: null,
  };
}

function mockClient(items: ReviewItem[]) {
  const decide = vi.fn().mockImplementation((unitId: number) =>
    Promise.resolve({
      unit_id: unitId,
      decision: "approve",
      method: "human_approved",
      final_label_id: 5,
      value: { category: "cat" },
      confidence: 0.62,
      queue_depth: Math.max(0, items.length - 1),
      webhooks_fired: 0,
    }),
  );
  const client = {
    reviewQueue: vi.fn().mockResolvedValue({
      project_id: 1,
      depth: items.length,
      threshold: 25,
      items,
    }),
    reviewItem: vi
      .fn()
      .mockImplementation((unitId: number) =>
        Promise.resolve(detailOf(items.find((i) => i.unit_id === unitId) ?? items[0])),
      ),
    decideReview: decide,
  } as unknown as MiniLpClient & {
    reviewQueue: ReturnType<typeof vi.fn>;
    reviewItem: ReturnType<typeof vi.fn>;
    decideReview: ReturnType<typeof vi.fn>;
  };
  return client;
}

function renderReview(items: ReviewItem[]) {
  const client = mockClient(items);
  render(<Review client={client} projectId={1} />);
  return client;
}

// --- everything needed to decide, on one screen (§7.2) -----------------------

describe("a queue item shows the merged proposal and every vote behind it", () => {
  it("shows the proposed answer with its consensus and entropy", async () => {
    renderReview([item()]);
    await screen.findByTestId("review-proposal");
    expect(screen.getByTestId("review-proposed-value").textContent).toContain("cat");
    const head = screen.getByTestId("review-proposal");
    expect(head.textContent).toContain("calibration_weighted");
    expect(head.textContent).toContain("62%");
  });

  it("names each rater, its kind and the weight its vote carried", async () => {
    renderReview([item()]);
    const votes = await screen.findByTestId("review-votes");
    const judge = within(votes).getByTestId("review-vote-101");
    expect(judge.textContent).toContain("claude-judge");
    expect(judge.textContent).toContain("model");
    expect(judge.textContent).toContain("0.90");

    const human = within(votes).getByTestId("review-vote-102");
    expect(human.textContent).toContain("sam");
    expect(human.textContent).toContain("dog");
    expect(human.textContent).toContain("0.55");
  });

  it("shows the judges' reasoning traces inline", async () => {
    renderReview([item()]);
    const traces = await screen.findByTestId("review-traces");
    expect(traces.textContent).toContain("retractable claws");
  });

  it("says why the unit was escalated", async () => {
    renderReview([item()]);
    const reason = await screen.findByTestId("review-reason");
    expect(reason.textContent).toContain("without consensus");
    expect(reason.textContent).toContain("category");
  });

  it("reports the queue depth", async () => {
    renderReview([item(), item({ unit_id: 12 })]);
    expect((await screen.findByTestId("review-depth")).textContent).toContain("2 waiting");
  });
});

// --- one key press per decision ----------------------------------------------

describe("decisions are one key press and advance the queue", () => {
  it("approves with `a`, sending the decision and moving on", async () => {
    const client = renderReview([item(), item({ unit_id: 12 })]);
    await screen.findByTestId("review-proposal");

    fireEvent.keyDown(window, { key: "a" });
    await waitFor(() =>
      expect(client.decideReview).toHaveBeenCalledWith(11, {
        decision: "approve",
        value: undefined,
        comment: undefined,
      }),
    );
    // Advanced: the next unit is now the one on screen.
    await waitFor(() => expect(screen.getByTestId("review-unit").textContent).toContain("#12"));
  });

  it("walks the queue with n and p", async () => {
    renderReview([item(), item({ unit_id: 12 })]);
    await screen.findByTestId("review-unit");
    expect(screen.getByTestId("review-unit").textContent).toContain("#11");

    fireEvent.keyDown(window, { key: "n" });
    await waitFor(() => expect(screen.getByTestId("review-unit").textContent).toContain("#12"));

    fireEvent.keyDown(window, { key: "p" });
    await waitFor(() => expect(screen.getByTestId("review-unit").textContent).toContain("#11"));
  });

  it("opens the override editor with `o` and closes it with escape", async () => {
    renderReview([item()]);
    await screen.findByTestId("review-proposal");
    expect(screen.queryByTestId("review-override")).toBeNull();

    fireEvent.keyDown(window, { key: "o" });
    await screen.findByTestId("review-override");

    fireEvent.keyDown(window, { key: "escape" });
    await waitFor(() => expect(screen.queryByTestId("review-override")).toBeNull());
  });

  it("sends the reviewer's own answer, canonicalized, on override", async () => {
    const client = renderReview([item()]);
    await screen.findByTestId("review-proposal");
    fireEvent.keyDown(window, { key: "o" });
    await screen.findByTestId("review-override");

    // The override editor renders the template's real widgets, so picking an
    // answer is the same gesture as in the annotation view.
    const override = screen.getByTestId("review-override");
    fireEvent.click(within(override).getByTestId("category-opt-bird"));
    fireEvent.change(screen.getByTestId("review-comment"), {
      target: { value: "both raters misread it" },
    });
    fireEvent.click(screen.getByTestId("review-override-submit"));

    await waitFor(() =>
      expect(client.decideReview).toHaveBeenCalledWith(11, {
        decision: "override",
        value: { category: "bird" },
        comment: "both raters misread it",
      }),
    );
  });

  it("will not submit an incomplete override", async () => {
    const client = renderReview([item()]);
    await screen.findByTestId("review-proposal");
    fireEvent.keyDown(window, { key: "o" });
    await screen.findByTestId("review-override");

    expect(screen.getByTestId("review-override-submit")).toBeDisabled();
    fireEvent.keyDown(window, { key: "enter" });
    expect(client.decideReview).not.toHaveBeenCalled();
  });

  it("does not approve while the override editor is open", async () => {
    // `a` is a plausible thing to type into a comment box; approving out from
    // under a half-written override would be the worst kind of surprise.
    const client = renderReview([item()]);
    await screen.findByTestId("review-proposal");
    fireEvent.keyDown(window, { key: "o" });
    await screen.findByTestId("review-override");

    fireEvent.keyDown(window, { key: "a" });
    expect(client.decideReview).not.toHaveBeenCalled();
  });
});

// --- the edges ---------------------------------------------------------------

describe("edge states", () => {
  it("shows a queue-specific empty state, not a generic blank", async () => {
    renderReview([]);
    const empty = await screen.findByTestId("review-empty");
    expect(empty.textContent).toContain("Nothing to review");
    expect(empty.textContent).toContain("routing pipeline");
  });

  it("refuses to offer Approve when there is nothing to merge", async () => {
    renderReview([item({ proposal: null })]);
    await screen.findByTestId("review-no-proposal");
    expect(screen.getByTestId("review-approve")).toBeDisabled();
    // Overriding is still available — that is the only way to decide such a unit.
    expect(screen.getByTestId("review-override-toggle")).not.toBeDisabled();
  });

  it("surfaces a failed decision instead of silently losing it", async () => {
    const client = renderReview([item()]);
    await screen.findByTestId("review-proposal");
    client.decideReview.mockRejectedValueOnce(new Error("unit already decided"));

    fireEvent.keyDown(window, { key: "a" });
    await waitFor(() =>
      expect(screen.getByTestId("review-error").textContent).toContain("already decided"),
    );
    // Still on the same unit: a failed decision must not look like a success.
    expect(screen.getByTestId("review-unit").textContent).toContain("#11");
  });

  it("surfaces a failed queue fetch", async () => {
    const client = {
      reviewQueue: vi.fn().mockRejectedValue(new Error("forbidden")),
      reviewItem: vi.fn(),
      decideReview: vi.fn(),
    } as unknown as MiniLpClient;
    render(<Review client={client} projectId={1} />);
    await waitFor(() =>
      expect(screen.getByTestId("review-error").textContent).toContain("forbidden"),
    );
  });
});
