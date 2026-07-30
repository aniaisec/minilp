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

import { useCallback, useEffect } from "react";

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
  confirmMessage?: string;
  label?: string;
  /** Off for screens where a global letter key would collide (e.g. admin forms). */
  hotkey?: boolean;
  disabled?: boolean;
}

export function ExitToHome({
  href,
  onLeave,
  dirty = false,
  confirmMessage = "Discard your unsubmitted answer and return to your tasks?",
  label = "Home",
  hotkey = true,
  disabled = false,
}: ExitToHomeProps) {
  const leave = useCallback(async () => {
    if (disabled) return;
    if (dirty && !window.confirm(confirmMessage)) return;
    try {
      await onLeave?.();
    } catch {
      /* the lease expires on its own; never trap the annotator here */
    }
    window.location.search = href.startsWith("?") ? href : `?${href}`;
  }, [disabled, dirty, confirmMessage, onLeave, href]);

  useEffect(() => {
    if (!hotkey) return;
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (eventToken(e) !== EXIT_HOTKEY) return;
      e.preventDefault();
      void leave();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [hotkey, leave]);

  return (
    <button
      type="button"
      className="mlp-btn mlp-btn-exit"
      onClick={() => void leave()}
      disabled={disabled}
      data-testid="btn-home"
      title="Return to your tasks; any held task is released"
    >
      ← {label}
      {hotkey ? ` (${EXIT_HOTKEY})` : ""}
    </button>
  );
}
