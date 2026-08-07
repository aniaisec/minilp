// M8 acceptance — exit to home (§11, §12).
//
// The acceptance criterion is a DB claim: "exiting a project mid-task reopens
// its slot with the variant intact (asserted in the DB, not just the UI)". The
// DB half lives in the backend suite — `skip` reopening a slot with its variant
// retained is asserted there (§2.7, `test_slots.py` / `test_assignment.py`).
// What *this* suite owns is the other half: that leaving actually calls `skip`
// on the held slot, with the right slot id, before navigating — because a UI
// that navigates without releasing would leave the backend correct and the pool
// starved anyway.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TaskClient } from "../api/client";
import type { Task } from "../api/types";
import { ExitToHome } from "../components/ExitToHome";
import { IMAGE_CLASSIFICATION } from "../fixtures/gallery";
import { RESERVED_ACTION_KEYS } from "../hotkeys/assign";
import { Annotate } from "./Annotate";

function makeTask(): Task {
  return {
    slot_id: 42,
    unit_id: 7,
    project_id: 1,
    payload: { image_url: "http://x/1.png" },
    variant: null,
  };
}

function mockClient(task: Task) {
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
  } as TaskClient & { skip: ReturnType<typeof vi.fn>; submit: ReturnType<typeof vi.fn> };
}

/** jsdom refuses real navigation; capture the assignment instead. */
function stubNavigation() {
  const search = { value: "" };
  Object.defineProperty(window, "location", {
    configurable: true,
    value: {
      ...window.location,
      pathname: "/",
      get search() {
        return search.value;
      },
      set search(v: string) {
        search.value = v;
      },
    },
  });
  return search;
}

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* no storage */
  }
  vi.restoreAllMocks();
});

// --- the control itself ------------------------------------------------------

describe("ExitToHome", () => {
  it("releases the lease, then navigates home", async () => {
    const nav = stubNavigation();
    const onLeave = vi.fn().mockResolvedValue(undefined);
    render(<ExitToHome href="?annotator=9&key=k" onLeave={onLeave} />);

    fireEvent.click(screen.getByTestId("btn-home"));
    await waitFor(() => expect(onLeave).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(nav.value).toBe("?annotator=9&key=k"));
  });

  it("leaves anyway when releasing the lease fails", async () => {
    // Being trapped in a project is worse than a stale lease, which expires.
    const nav = stubNavigation();
    const onLeave = vi.fn().mockRejectedValue(new Error("network"));
    render(<ExitToHome href="?annotator=9" onLeave={onLeave} />);

    fireEvent.click(screen.getByTestId("btn-home"));
    await waitFor(() => expect(nav.value).toBe("?annotator=9"));
  });

  // Phase 7 replaced `window.confirm` here with the shared dialog. These tests
  // no longer stub a global, which is itself part of the point: the previous
  // versions could only assert that *a* native prompt appeared, never what it
  // said or which button kept the annotator's work.
  it("warns before discarding an unsubmitted answer, and stays put if declined", async () => {
    const nav = stubNavigation();
    const onLeave = vi.fn();
    render(<ExitToHome href="?annotator=9" onLeave={onLeave} dirty />);

    fireEvent.click(screen.getByTestId("btn-home"));
    const dialog = await screen.findByTestId("exit-confirm");
    expect(dialog).toHaveTextContent("Discard your unsubmitted answer?");

    fireEvent.click(screen.getByTestId("confirm-cancel"));
    await waitFor(() => expect(screen.queryByTestId("exit-confirm")).not.toBeInTheDocument());
    expect(onLeave).not.toHaveBeenCalled();
    expect(nav.value).toBe("");
  });

  it("names both buttons after what they do, not after the click", async () => {
    // The whole complaint against `window.confirm`: "OK" and "Cancel" gave no
    // clue which one kept the work.
    stubNavigation();
    render(<ExitToHome href="?annotator=9" dirty />);
    fireEvent.click(screen.getByTestId("btn-home"));

    expect(await screen.findByTestId("confirm-accept")).toHaveTextContent("Discard and leave");
    expect(screen.getByTestId("confirm-cancel")).toHaveTextContent("Keep working");
  });

  it("leaves once the discard is confirmed", async () => {
    const nav = stubNavigation();
    const onLeave = vi.fn().mockResolvedValue(undefined);
    render(<ExitToHome href="?annotator=9" onLeave={onLeave} dirty />);

    fireEvent.click(screen.getByTestId("btn-home"));
    fireEvent.click(await screen.findByTestId("confirm-accept"));

    // Confirming runs the same departure the clean path runs — the lease is
    // still released before navigating.
    await waitFor(() => expect(onLeave).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(nav.value).toBe("?annotator=9"));
  });

  it("ignores the exit hotkey while its own dialog is open", async () => {
    // Otherwise a held or repeated `x` reopens exit from inside the modal it
    // just opened.
    const nav = stubNavigation();
    render(<ExitToHome href="?annotator=9" dirty />);

    fireEvent.keyDown(window, { key: "x" });
    await screen.findByTestId("exit-confirm");
    fireEvent.keyDown(window, { key: "x" });

    expect(screen.getAllByTestId("exit-confirm")).toHaveLength(1);
    expect(nav.value).toBe("");
  });

  it("does not warn when there is nothing unsubmitted", async () => {
    const nav = stubNavigation();
    render(<ExitToHome href="?annotator=9" dirty={false} />);
    fireEvent.click(screen.getByTestId("btn-home"));

    await waitFor(() => expect(nav.value).toBe("?annotator=9"));
    expect(screen.queryByTestId("exit-confirm")).not.toBeInTheDocument();
  });

  it("responds to its hotkey, but not while typing", async () => {
    const nav = stubNavigation();
    render(
      <>
        <ExitToHome href="?annotator=9" />
        <textarea data-testid="notes" />
      </>,
    );

    fireEvent.keyDown(screen.getByTestId("notes"), { key: "x" });
    expect(nav.value).toBe("");

    fireEvent.keyDown(window, { key: "x" });
    await waitFor(() => expect(nav.value).toBe("?annotator=9"));
  });

  it("ignores the key when it is part of a browser shortcut", () => {
    const nav = stubNavigation();
    render(<ExitToHome href="?annotator=9" />);
    fireEvent.keyDown(window, { key: "x", ctrlKey: true }); // Ctrl+X = cut
    fireEvent.keyDown(window, { key: "x", metaKey: true });
    expect(nav.value).toBe("");
  });

  it("can drop the hotkey and stay a plain button", () => {
    const nav = stubNavigation();
    render(<ExitToHome href="?annotator=9" hotkey={false} />);
    fireEvent.keyDown(window, { key: "x" });
    expect(nav.value).toBe("");
    expect(screen.getByTestId("btn-home").textContent).not.toContain("(x)");
  });
});

// --- the key it chose (§2.4) -------------------------------------------------

describe("the exit hotkey was chosen without colliding", () => {
  it("is reserved, so auto-assignment can never hand it to an option", () => {
    // §11: Esc was the natural key and is already "clear selection", so the
    // exit key had to be picked without a collision — §2.4's mechanism for that
    // is the reserved set, not hoping no template uses the letter.
    expect(RESERVED_ACTION_KEYS.has("x")).toBe(true);
    expect(RESERVED_ACTION_KEYS.has("escape")).toBe(true);
  });
});

// --- wired into the annotation view ------------------------------------------

describe("the annotation view exits by releasing its held slot", () => {
  it("skips the slot it holds, then lands on home", async () => {
    const nav = stubNavigation();
    const client = mockClient(makeTask());
    render(
      <Annotate
        client={client}
        annotatorId={9}
        projectId={1}
        schema={IMAGE_CLASSIFICATION}
        guidelines=""
        homeHref="?annotator=9&key=k"
      />,
    );
    await screen.findByTestId("btn-home");

    fireEvent.click(screen.getByTestId("btn-home"));
    // The same `skip` the `s` key uses — so the slot reopens now, variant
    // retained (§2.7), rather than sitting leased until the lease expires.
    await waitFor(() => expect(client.skip).toHaveBeenCalledWith(42, 9));
    await waitFor(() => expect(nav.value).toBe("?annotator=9&key=k"));
  });

  it("warns first when an answer has been started but not submitted", async () => {
    stubNavigation();
    const client = mockClient(makeTask());
    render(
      <Annotate
        client={client}
        annotatorId={9}
        projectId={1}
        schema={IMAGE_CLASSIFICATION}
        guidelines=""
        homeHref="?annotator=9"
      />,
    );
    await screen.findByTestId("btn-home");

    // Pick an answer without submitting it.
    fireEvent.keyDown(window, { key: "1" });
    fireEvent.click(screen.getByTestId("btn-home"));

    await screen.findByTestId("exit-confirm");
    // Crucially, the slot is *not* released until the discard is confirmed —
    // opening the dialog must not be half a departure.
    expect(client.skip).not.toHaveBeenCalled();
  });

  it("stands the annotation hotkeys down while the discard dialog is up", async () => {
    // The one that `window.confirm` used to get for free by blocking the event
    // loop. Without an explicit guard, Enter behind this dialog *submits* the
    // answer it is offering to discard, `s` skips the task, and the option keys
    // edit the very thing under discussion — the focus trap cannot stop a
    // window-level listener.
    stubNavigation();
    const client = mockClient(makeTask());
    render(
      <Annotate
        client={client}
        annotatorId={9}
        projectId={1}
        schema={IMAGE_CLASSIFICATION}
        guidelines=""
        homeHref="?annotator=9"
      />,
    );
    await screen.findByTestId("btn-home");

    fireEvent.keyDown(window, { key: "1" });
    fireEvent.click(screen.getByTestId("btn-home"));
    await screen.findByTestId("exit-confirm");

    fireEvent.keyDown(window, { key: "Enter" });
    fireEvent.keyDown(window, { key: "s" });
    fireEvent.keyDown(window, { key: "?" });

    expect(client.submit).not.toHaveBeenCalled();
    expect(client.skip).not.toHaveBeenCalled();
    expect(screen.queryByTestId("hotkey-overlay")).not.toBeInTheDocument();
    expect(screen.getByTestId("exit-confirm")).toBeInTheDocument();
  });

  it("never warns about a submitted answer", async () => {
    const nav = stubNavigation();
    const client = mockClient(makeTask());
    render(
      <Annotate
        client={client}
        annotatorId={9}
        projectId={1}
        schema={IMAGE_CLASSIFICATION}
        guidelines=""
        homeHref="?annotator=9"
      />,
    );
    await screen.findByTestId("btn-home");

    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => expect(client.submit).toHaveBeenCalled());
    await screen.findByTestId("empty-queue");

    fireEvent.click(screen.getByTestId("btn-home"));
    await waitFor(() => expect(nav.value).toBe("?annotator=9"));
    expect(screen.queryByTestId("exit-confirm")).not.toBeInTheDocument();
  });

  it("renders no exit control when there is nowhere to go back to", async () => {
    const client = mockClient(makeTask());
    render(
      <Annotate
        client={client}
        annotatorId={9}
        projectId={1}
        schema={IMAGE_CLASSIFICATION}
        guidelines=""
      />,
    );
    await screen.findByTestId("btn-submit");
    expect(screen.queryByTestId("btn-home")).toBeNull();
  });

  it("completes a keyboard-only round trip: label, then exit", async () => {
    // §12 M8: "home → project → label → exit → home, zero mouse events."
    // The home→project leg is a link (asserted in Home.test.tsx); this is the
    // leg that happens inside the annotation view, with no click anywhere.
    const nav = stubNavigation();
    const client = mockClient(makeTask());
    render(
      <Annotate
        client={client}
        annotatorId={9}
        projectId={1}
        schema={IMAGE_CLASSIFICATION}
        guidelines=""
        homeHref="?annotator=9&key=k"
      />,
    );
    await screen.findByTestId("btn-home");

    fireEvent.keyDown(window, { key: "1" }); // pick
    fireEvent.keyDown(window, { key: "Enter" }); // submit
    await waitFor(() => expect(client.submit).toHaveBeenCalled());

    fireEvent.keyDown(window, { key: "x" }); // exit
    await waitFor(() => expect(nav.value).toBe("?annotator=9&key=k"));
  });
});
