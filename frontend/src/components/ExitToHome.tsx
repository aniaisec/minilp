// Exit to home (M8, §11) — the control every project screen carries.
//
// Two details are the whole feature:
//
// **Leaving releases the lease.** The annotation view hands `onLeave` the same
// `skip` call the `s` key uses, so the slot reopens *now* with its variant
// retained (§2.7) instead of sitting leased until it expires. A person who
// wanders off has, in effect, already skipped; making them wait out a 30-minute
// lease penalises everyone else in the pool.
//
// **The hotkey is not Escape.** `Esc` is reserved for "clear selection / close
// overlay" (§2.4), and rebinding it here would make backing out of a dropdown
// occasionally quit the task instead. `x` is free, adjacent to nothing
// destructive, and shown on the control — and the control stays a real button,
// so tab-and-Enter works for anyone who never learns the key.
//
// Phase 7 replaced the `window.confirm` that guarded the dirty case. The native
// dialog's buttons said "OK" and "Cancel", which is the worst possible pair
// here: the thing being confirmed is *discarding work*, and "OK" names neither
// the discarding nor the work. See `ConfirmDialog` for the rest of the argument.

import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog } from "./ConfirmDialog";
import { eventToken, isTypingTarget } from "../hotkeys/event";

export const EXIT_HOTKEY = "x";

export interface ExitToHomeProps {
  /** Where "home" is. */
  href: string;
  /** Released before leaving (the held lease). May be async; failures never trap
   *  the annotator on the page — being stuck in a project is worse than a stale
   *  lease, which expires on its own anyway. */
  onLeave?: () => Promise<void> | void;
  /** True when there is unsubmitted work worth warning about (§11). */
  dirty?: boolean;
  /** Body of the confirmation, shown under the heading. */
  confirmMessage?: string;
  /**
   * Raised while the confirmation is open. The surface around this control
   * usually owns a window-level hotkey dispatcher, and that dispatcher has to
   * stand down while a modal is up — a child cannot reach it, so it is told.
   */
  onConfirmingChange?: (confirming: boolean) => void;
  label?: string;
  /** Off for screens where a global letter key would collide (e.g. admin forms). */
  hotkey?: boolean;
  disabled?: boolean;
}

export function ExitToHome({
  href,
  onLeave,
  dirty = false,
  confirmMessage = "Your answer has not been submitted. Leaving discards it and reopens the task for someone else.",
  onConfirmingChange,
  label = "Home",
  hotkey = true,
  disabled = false,
}: ExitToHomeProps) {
  const [confirming, setConfirming] = useState(false);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    onConfirmingChange?.(confirming);
  }, [confirming, onConfirmingChange]);

  // The half that actually leaves. Split from `request` so the dialog's confirm
  // button and the clean-exit path are the same code — a confirmation that runs
  // a second, slightly different departure routine is how the two drift.
  //
  // The dialog stays up, in its `busy` state, until the lease release settles.
  // Closing it first left the annotator looking at an unchanged screen with no
  // sign anything was happening, and `x` free to reopen it mid-departure.
  const go = useCallback(async () => {
    setLeaving(true);
    try {
      await onLeave?.();
    } catch {
      /* the lease expires on its own; never trap the annotator here */
    }
    setConfirming(false);
    setLeaving(false);
    window.location.search = href.startsWith("?") ? href : `?${href}`;
  }, [onLeave, href]);

  const request = useCallback(() => {
    if (disabled || leaving) return;
    if (dirty) {
      setConfirming(true);
      return;
    }
    void go();
  }, [disabled, dirty, leaving, go]);

  useEffect(() => {
    if (!hotkey) return;
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (eventToken(e) !== EXIT_HOTKEY) return;
      // While the dialog is up, `x` is not the exit key any more — it is a
      // keystroke inside a modal, and re-arming exit from in there would let a
      // repeated keypress confirm the very dialog it opened.
      if (confirming) return;
      e.preventDefault();
      request();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [hotkey, request, confirming]);

  return (
    <>
      <button
        type="button"
        className="mlp-btn mlp-btn-exit"
        onClick={request}
        disabled={disabled}
        data-testid="btn-home"
        title="Return to your tasks; any held task is released"
      >
        ← {label}
        {hotkey ? ` (${EXIT_HOTKEY})` : ""}
      </button>

      {confirming && (
        <ConfirmDialog
          title="Discard your unsubmitted answer?"
          // Named after what is lost, not after the click. "OK" — which is what
          // `window.confirm` offered — told the annotator nothing about which
          // of the two buttons kept their work.
          confirmLabel="Discard and leave"
          cancelLabel="Keep working"
          busy={leaving}
          busyLabel="Leaving…"
          data-testid="exit-confirm"
          onConfirm={() => void go()}
          onCancel={() => setConfirming(false)}
        >
          {confirmMessage}
        </ConfirmDialog>
      )}
    </>
  );
}
