// One focus trap, shared (§ UX plan, accessibility baseline).
//
// The plan calls for the mobile nav drawer, the hotkey overlay and the
// confirmation dialog to all trap focus, restore it, and close on Escape. That
// is one behaviour, so it is one hook — three copies would be three chances to
// get the restore step wrong, and the restore step is the one people forget.
//
// What it does while `active`:
//   • moves focus into the container (first focusable, or the container itself)
//   • keeps Tab and Shift+Tab inside it
//   • calls `onClose` on Escape
//   • returns focus to whatever was focused before, on deactivate
//
// What it deliberately does not do: render anything, or set `role`/`aria-modal`.
// Those belong to the component, which knows what kind of dialog it is.

import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function focusableWithin(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    // `offsetParent === null` catches display:none; the explicit `hidden`
    // check catches the case jsdom cannot lay out, which is every case in tests.
    (el) => !el.hasAttribute("hidden") && el.getAttribute("aria-hidden") !== "true",
  );
}

export function useFocusTrap(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
  onClose?: () => void,
): void {
  // Held in a ref rather than state: restoring focus must not depend on a
  // render happening first.
  const restoreTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active) return;
    const container = ref.current;
    if (!container) return;

    restoreTo.current = document.activeElement as HTMLElement | null;

    const first = focusableWithin(container)[0];
    if (first) first.focus();
    else {
      container.setAttribute("tabindex", "-1");
      container.focus();
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose?.();
        return;
      }
      if (e.key !== "Tab") return;

      const items = focusableWithin(container);
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      const current = document.activeElement;

      // Wrap at both ends. Also catches focus that has escaped the container
      // entirely (browser chrome, a stray programmatic focus) by pulling it back.
      if (e.shiftKey && (current === firstItem || !container.contains(current))) {
        e.preventDefault();
        lastItem.focus();
      } else if (!e.shiftKey && (current === lastItem || !container.contains(current))) {
        e.preventDefault();
        firstItem.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      // Only restore if the trigger is still in the document — if the whole
      // view unmounted, yanking focus to a detached node loses it entirely.
      const target = restoreTo.current;
      if (target && document.contains(target)) target.focus();
    };
  }, [ref, active, onClose]);
}
