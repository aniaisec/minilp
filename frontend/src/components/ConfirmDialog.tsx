// Confirmation dialog (§ UX plan, phase 7) — one component, replacing
// `window.confirm` and the hand-rolled inline confirmations.
//
// What was wrong with `window.confirm`: it cannot be styled, so it looks like
// it belongs to the browser rather than the app; its buttons are "OK" and
// "Cancel", so the destructive action is named after the act of clicking rather
// than after what it destroys; it blocks the event loop; and it cannot be
// driven from a test without stubbing a global.
//
// **Why the native `<dialog>`.** It is the only element that gets the top
// layer, so the dialog cannot be painted over by a sticky header or trapped
// under a stacking context, and `::backdrop` comes free. `showModal()` also
// makes the rest of the page inert, which no amount of `role="dialog"` on a
// `<div>` will do.
//
// Two things follow from that, and both are here rather than in the caller:
//
//   • jsdom (25) does not implement `showModal`, so `src/test/setup.ts` shims
//     it. The shim is deliberately thin — it does not fake the top layer or
//     inertness, so anything this component needs beyond "the dialog is open"
//     has to be real behaviour, not a property of the shim.
//   • Escape is handled once. The native `cancel` event is preventDefault'd and
//     the shared focus trap's Escape is the only path to `onCancel`, so the
//     behaviour under jsdom and in a browser is the same code, and focus is
//     restored to the trigger either way.

import { useCallback, useId, useLayoutEffect, useRef, type ReactNode } from "react";

import { Button } from "./ui";
import { useFocusTrap } from "../hooks/useFocusTrap";

export interface ConfirmDialogProps {
  /** The question, as a heading. "Delete this template?" — not "Are you sure?" */
  title: ReactNode;
  /** What confirming will actually do, including anything that cannot be undone. */
  children?: ReactNode;
  /**
   * The confirm button's label, and the reason this component exists: it names
   * the action ("Delete 3 versions") rather than the click ("OK"). Required,
   * because a default would immediately become "OK" everywhere.
   */
  confirmLabel: string;
  cancelLabel?: string;
  /** `danger` for anything that destroys data — most callers. */
  tone?: "danger" | "primary";
  /** Disables both buttons and relabels confirm while the action is in flight. */
  busy?: boolean;
  busyLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  "data-testid"?: string;
}

export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "danger",
  busy = false,
  busyLabel,
  onConfirm,
  onCancel,
  "data-testid": testId = "confirm-dialog",
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement | null>(null);
  const titleId = useId();
  const bodyId = useId();

  // A dialog that is dismissed while its action is running would leave the
  // caller finishing an operation nobody is watching. Escape is ignored until
  // it settles; the buttons are disabled for the same reason.
  const cancel = useCallback(() => {
    if (!busy) onCancel();
  }, [busy, onCancel]);

  // Opened BEFORE the trap installs, and in a layout effect. A closed
  // `<dialog>` is `display: none` under the UA stylesheet, so a `focus()` call
  // against anything inside it is a no-op — running the trap first would mean
  // the focus placement below only appeared to work, by coincidence of
  // `showModal()` landing on the same button.
  useLayoutEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // `showModal` rather than `show`: the modal form is the one that gets the
    // top layer and makes the background inert.
    if (!dialog.open) dialog.showModal?.();
    return () => {
      if (dialog.open) dialog.close?.();
    };
  }, []);

  useFocusTrap(ref, true, cancel);

  return (
    <dialog
      ref={ref}
      className="mlp-dialog"
      aria-labelledby={titleId}
      // Truthiness, not `!== undefined`: `{cond && <p/>}` yields `false`,
      // which would otherwise wire `aria-describedby` to an empty element.
      aria-describedby={children ? bodyId : undefined}
      data-testid={testId}
      // Native Escape fires `cancel`; the focus trap already handles Escape and
      // is the path that also restores focus, so this one is suppressed rather
      // than run alongside it.
      onCancel={(e) => e.preventDefault()}
      // Clicking the backdrop lands on the <dialog> itself, since its children
      // sit inside the inner div. Treated as cancel, which is the safe answer
      // for a dialog whose other button destroys something.
      onClick={(e) => {
        if (e.target === ref.current) cancel();
      }}
    >
      <div className="mlp-dialog-body">
        <h2 className="mlp-dialog-title" id={titleId}>
          {title}
        </h2>
        {children ? (
          <div className="mlp-dialog-text" id={bodyId}>
            {children}
          </div>
        ) : null}
        <div className="mlp-dialog-actions">
          {/* Cancel first in the DOM so it is the first thing focus lands on:
              the trap focuses the first control, and the first control of a
              destructive dialog should not be the destructive one. */}
          <Button data-testid="confirm-cancel" disabled={busy} onClick={cancel}>
            {cancelLabel}
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "primary"}
            data-testid="confirm-accept"
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? (busyLabel ?? `${confirmLabel}…`) : confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
