// Phase 7 — the confirmation dialog.
//
// The plan's line is that "the mobile drawer, hotkey overlay, and confirmation
// dialog each trap focus and restore it to their trigger". The trap itself is
// `useFocusTrap` and is exercised through the drawer and the overlay already;
// what is tested here is this component's own decisions — that it opens modally,
// that Escape and the backdrop both mean *cancel* rather than confirm, that the
// safe control is the one focus lands on, and that a dialog mid-action cannot
// be dismissed out from under the operation it started.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./ConfirmDialog";

function open(props: Partial<React.ComponentProps<typeof ConfirmDialog>> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      title="Delete “my-template” v1?"
      confirmLabel="Delete version"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...props}
    >
      This version is removed. This cannot be undone.
    </ConfirmDialog>,
  );
  return { onConfirm, onCancel };
}

describe("ConfirmDialog", () => {
  it("opens as a modal dialog, named by its heading and described by its body", () => {
    open();
    const dialog = screen.getByTestId("confirm-dialog");
    expect(dialog.tagName).toBe("DIALOG");
    // `showModal`, not `show`: the modal form is the one that gets the top
    // layer and makes the rest of the page inert.
    expect((dialog as HTMLDialogElement).open).toBe(true);
    expect(dialog).toHaveAccessibleName("Delete “my-template” v1?");
    expect(dialog).toHaveAccessibleDescription(/This cannot be undone/);
  });

  it("names the destructive action rather than the click", () => {
    // The entire case against `window.confirm`, in one assertion: its buttons
    // were "OK" and "Cancel", neither of which says what is about to happen.
    open();
    expect(screen.getByTestId("confirm-accept")).toHaveTextContent("Delete version");
    expect(screen.getByTestId("confirm-accept")).not.toHaveTextContent(/^OK$/);
  });

  it("lands focus on the safe control, not the destructive one", async () => {
    open();
    await waitFor(() => expect(screen.getByTestId("confirm-cancel")).toHaveFocus());
  });

  it("confirms and cancels through their own callbacks", () => {
    const { onConfirm, onCancel } = open();
    fireEvent.click(screen.getByTestId("confirm-accept"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("confirm-cancel"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("treats Escape as cancel", () => {
    const { onConfirm, onCancel } = open();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("treats a backdrop click as cancel, not as confirm", () => {
    // Clicking outside a destructive dialog has to resolve to the safe answer.
    const { onConfirm, onCancel } = open();
    fireEvent.click(screen.getByTestId("confirm-dialog"));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("does not cancel when the click lands inside the dialog's own body", () => {
    const { onCancel } = open();
    fireEvent.click(screen.getByText(/This cannot be undone/));
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("cannot be dismissed while its action is in flight", () => {
    // A dialog dismissed mid-delete leaves the caller finishing an operation
    // nobody is watching.
    const { onConfirm, onCancel } = open({ busy: true, busyLabel: "Deleting…" });
    expect(screen.getByTestId("confirm-accept")).toBeDisabled();
    expect(screen.getByTestId("confirm-accept")).toHaveTextContent("Deleting…");
    expect(screen.getByTestId("confirm-cancel")).toBeDisabled();

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByTestId("confirm-dialog"));
    expect(onCancel).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("restores focus to whatever opened it", async () => {
    // The step people forget: dismissing a dialog and dropping focus on
    // <body> strands a keyboard user at the top of the document.
    function Host() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button data-testid="trigger" onClick={() => setOpen(true)}>
            Delete
          </button>
          {open && (
            <ConfirmDialog
              title="Delete?"
              confirmLabel="Delete version"
              onConfirm={() => setOpen(false)}
              onCancel={() => setOpen(false)}
            />
          )}
        </>
      );
    }
    render(<Host />);
    const trigger = screen.getByTestId("trigger");
    trigger.focus();
    fireEvent.click(trigger);

    await waitFor(() => expect(screen.getByTestId("confirm-cancel")).toHaveFocus());
    fireEvent.click(screen.getByTestId("confirm-cancel"));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("keeps Tab inside itself", async () => {
    open();
    const cancel = screen.getByTestId("confirm-cancel");
    const accept = screen.getByTestId("confirm-accept");
    await waitFor(() => expect(cancel).toHaveFocus());

    // Forward off the last control wraps to the first, rather than escaping to
    // the page behind the modal.
    accept.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(cancel).toHaveFocus();

    // And backwards off the first wraps to the last.
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(accept).toHaveFocus();
  });
});
