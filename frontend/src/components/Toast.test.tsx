// Phase 7 — toasts.
//
// The four properties worth a test are the four that are easy to get wrong and
// invisible when they are: that an error stays put, that a success does not,
// that the two land in regions with different politeness, and that a dismissed
// toast takes its pending timer with it.

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TOAST_DURATION, ToastProvider, useToast } from "./Toast";

/** A bare surface with one button per kind of message. */
function Harness() {
  const toast = useToast();
  return (
    <div>
      <button data-testid="post-success" onClick={() => toast.success("Exported 12 rows.", "a.jsonl")}>
        success
      </button>
      <button data-testid="post-error" onClick={() => toast.error("The export failed.", "boom")}>
        error
      </button>
      <button data-testid="post-info" onClick={() => toast.show({ title: "Working…" })}>
        info
      </button>
    </div>
  );
}

function renderHarness() {
  return render(
    <ToastProvider>
      <Harness />
    </ToastProvider>,
  );
}

describe("ToastProvider", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it("shows a success with its detail, and clears itself", async () => {
    renderHarness();
    fireEvent.click(screen.getByTestId("post-success"));

    const toast = await screen.findByTestId("toast");
    expect(toast).toHaveTextContent("Exported 12 rows.");
    expect(toast).toHaveTextContent("a.jsonl");

    act(() => void vi.advanceTimersByTime(TOAST_DURATION + 10));
    await waitFor(() => expect(screen.queryByTestId("toast")).not.toBeInTheDocument());
  });

  it("never auto-dismisses an error", async () => {
    // The rule the whole component exists for: a message that disappears
    // before it can be read is worse than no message.
    renderHarness();
    fireEvent.click(screen.getByTestId("post-error"));
    await screen.findByTestId("toast");

    act(() => void vi.advanceTimersByTime(TOAST_DURATION * 20));
    expect(screen.getByTestId("toast")).toHaveTextContent("The export failed.");
  });

  it("dismisses on request, and does not fire the timer afterwards", async () => {
    renderHarness();
    fireEvent.click(screen.getByTestId("post-success"));
    await screen.findByTestId("toast");

    fireEvent.click(screen.getByTestId("toast-dismiss"));
    await waitFor(() => expect(screen.queryByTestId("toast")).not.toBeInTheDocument());

    // Post a second one and let the *first* toast's original deadline pass. If
    // the cancelled timer were still armed it would now remove this one, since
    // the filter it closes over runs against whatever is on screen.
    fireEvent.click(screen.getByTestId("post-error"));
    act(() => void vi.advanceTimersByTime(TOAST_DURATION + 10));
    expect(screen.getByTestId("toast")).toBeInTheDocument();
  });

  it("routes failures to an assertive region and everything else to a polite one", async () => {
    // Two regions rather than one, because `aria-live` is a property of the
    // region: a single region cannot be polite for success and assertive for
    // failure at the same time.
    renderHarness();
    fireEvent.click(screen.getByTestId("post-error"));
    fireEvent.click(screen.getByTestId("post-success"));
    await waitFor(() => expect(screen.getAllByTestId("toast")).toHaveLength(2));

    const assertive = screen.getByRole("alert");
    const polite = screen.getByRole("status");
    expect(assertive).toHaveAttribute("aria-live", "assertive");
    expect(polite).toHaveAttribute("aria-live", "polite");
    expect(assertive).toHaveTextContent("The export failed.");
    expect(assertive).not.toHaveTextContent("Exported 12 rows.");
    expect(polite).toHaveTextContent("Exported 12 rows.");
  });

  it("mounts both live regions before anything is posted into them", () => {
    // A live region inserted at the same moment as its content is commonly not
    // announced at all — which is how a toast ships that no screen reader ever
    // reads. Both regions have to already be in the tree.
    renderHarness();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
  });

  it("does not repeat the message in the dismiss button's name", async () => {
    // The button sits inside the live region, so a name like "Dismiss:
    // Exported 12 rows." would have the title announced a second time as part
    // of the button — every toast read twice.
    renderHarness();
    fireEvent.click(screen.getByTestId("post-success"));
    const toast = await screen.findByTestId("toast");
    const dismiss = screen.getByTestId("toast-dismiss");
    expect(dismiss).toHaveAccessibleName("Dismiss");
    expect(toast.textContent).not.toMatch(/Exported 12 rows\.[\s\S]*Exported 12 rows\./);
  });

  it("honours duration: null by pinning the toast", async () => {
    // `??` would have swallowed this: it fires on null as well as undefined,
    // so the pin silently became the 5s default.
    function Pinned() {
      const toast = useToast();
      return (
        <button
          data-testid="post-pinned"
          onClick={() => toast.show({ title: "Still working…", duration: null })}
        >
          pin
        </button>
      );
    }
    render(
      <ToastProvider>
        <Pinned />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByTestId("post-pinned"));
    await screen.findByTestId("toast");

    act(() => void vi.advanceTimersByTime(TOAST_DURATION * 4));
    expect(screen.getByTestId("toast")).toHaveTextContent("Still working…");
  });

  it("marks both regions non-atomic, so one arrival does not re-read the stack", () => {
    // `role="alert"` and `role="status"` both imply aria-atomic="true", which
    // on a container means every new toast re-announces its siblings.
    renderHarness();
    expect(screen.getByTestId("toast-assertive")).toHaveAttribute("aria-atomic", "false");
    expect(screen.getByTestId("toast-polite")).toHaveAttribute("aria-atomic", "false");
  });

  it("stacks several at once, oldest first within a region", async () => {
    renderHarness();
    fireEvent.click(screen.getByTestId("post-success"));
    fireEvent.click(screen.getByTestId("post-info"));
    await waitFor(() => expect(screen.getAllByTestId("toast")).toHaveLength(2));
    expect(screen.getAllByTestId("toast")[0]).toHaveTextContent("Exported 12 rows.");
    expect(screen.getAllByTestId("toast")[1]).toHaveTextContent("Working…");
  });
});

describe("useToast outside a provider", () => {
  it("is a no-op rather than a crash", () => {
    // Panels in this app are rendered standalone constantly — in tests, and
    // inside the template gallery's live preview. A hook that threw would make
    // every one of those call sites carry a provider it does not need.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<Harness />);
    fireEvent.click(screen.getByTestId("post-error"));
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
