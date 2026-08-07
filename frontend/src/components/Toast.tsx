// Toasts (§ UX plan, phase 7) — the app's one way of saying "that worked".
//
// Before this, an operation in the admin surface had exactly one channel, and
// it was failure: `ErrorState` on the way down, silence on the way up. Export a
// file, save a template sample, register a webhook, run a judge — all of them
// completed with no acknowledgement at all, so the only way to know an export
// had happened was to go and look in the downloads folder.
//
// Three decisions are the whole component:
//
// **Errors never auto-dismiss.** A message that disappears before it can be
// read is worse than no message, because it also costs the reader the time
// spent wondering whether they saw something. Success is disposable; failure is
// not, so failure stays until it is dismissed.
//
// **Two live regions, not one.** The plan says "a single `aria-live` region —
// polite for success, assertive for failure", and that is one region too few:
// `aria-live` is a property of the *region*, so one region can only have one
// politeness. Putting `aria-live` on each toast instead does not work either —
// a live region inserted into the DOM at the same moment as its content is
// commonly not announced at all, which is the classic way to ship a toast that
// no screen reader ever reads. So: two regions, both mounted from the start,
// both empty until something arrives, stacked into what looks like one column.
//
// **`useToast()` works with no provider.** It returns no-ops instead of
// throwing. Panels in this app are rendered standalone constantly — in tests,
// and inside the template gallery's live preview — and a component that
// explodes when it is mounted outside its provider makes every one of those
// call sites carry a provider it does not otherwise need.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { IconAlert, IconCheck, IconClose } from "./icons";

export type ToastTone = "success" | "error" | "info";

export interface ToastOptions {
  /** The sentence. Short, past tense, and about what happened — not about the
   *  button that was pressed. */
  title: ReactNode;
  /** Optional detail underneath: a row count, a filename, a server message. */
  body?: ReactNode;
  tone?: ToastTone;
  /** Milliseconds. `null` pins the toast open. Errors ignore this and are
   *  always pinned. */
  duration?: number | null;
}

/** `duration` is consumed when the toast is queued and not carried on the
 *  stored record, so it is omitted rather than advertised and ignored. */
export interface Toast extends Omit<ToastOptions, "duration"> {
  id: number;
  tone: ToastTone;
}

export interface ToastApi {
  /** The general form. Returns the id, so a caller can dismiss it itself. */
  show: (options: ToastOptions) => number;
  success: (title: ReactNode, body?: ReactNode) => number;
  error: (title: ReactNode, body?: ReactNode) => number;
  dismiss: (id: number) => void;
  clear: () => void;
}

/** Success and info clear themselves; five seconds is about two readings of a
 *  one-line sentence, which is what these are. */
export const TOAST_DURATION = 5000;

const NOOP: ToastApi = {
  show: () => -1,
  success: () => -1,
  error: () => -1,
  dismiss: () => {},
  clear: () => {},
};

const ToastContext = createContext<ToastApi | null>(null);

/**
 * The queue plus the region. Mount it once per surface, outside everything that
 * might want to post to it.
 */
export function ToastProvider({ children }: { children?: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  // Timers are keyed by toast id so a manual dismiss can cancel the pending
  // auto-dismiss — otherwise the timer fires later against a recycled id and
  // closes an unrelated toast.
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const clear = useCallback(() => {
    for (const timer of timers.current.values()) clearTimeout(timer);
    timers.current.clear();
    setToasts([]);
  }, []);

  const show = useCallback(
    ({ title, body, tone = "info", duration }: ToastOptions) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, title, body, tone }]);

      // The one rule that is not configurable. `duration` is honoured for
      // success and info; an error is pinned no matter what the caller passes,
      // because the caller is never the one who has to read it.
      // `duration === undefined`, not `??`: `??` also fires on `null`, which is
      // the documented way to pin a toast open — so `duration: null` would have
      // silently got the 5s default and dismissed itself.
      const ms =
        tone === "error" ? null : duration === undefined ? TOAST_DURATION : duration;
      if (ms !== null) {
        timers.current.set(
          id,
          setTimeout(() => {
            timers.current.delete(id);
            setToasts((current) => current.filter((t) => t.id !== id));
          }, ms),
        );
      }
      return id;
    },
    [],
  );

  // Unmounting with timers outstanding would fire `setToasts` on a dead tree.
  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of pending.values()) clearTimeout(timer);
      pending.clear();
    };
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (title, body) => show({ title, body, tone: "success" }),
      error: (title, body) => show({ title, body, tone: "error" }),
      dismiss,
      clear,
    }),
    [show, dismiss, clear],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastRegion toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

/**
 * Post a toast. Outside a `ToastProvider` every method is a no-op — see the
 * header for why that is deliberate rather than a missing invariant.
 */
export function useToast(): ToastApi {
  return useContext(ToastContext) ?? NOOP;
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  return (
    <div className={`mlp-toast mlp-toast-${toast.tone}`} data-testid="toast">
      <span className="mlp-toast-icon" aria-hidden="true">
        {/* Info gets the alert glyph rather than a tick: a checkmark beside
            "Building the bundle…" claims something finished that hasn't. */}
        {toast.tone === "success" ? <IconCheck size={18} /> : <IconAlert size={18} />}
      </span>
      <div className="mlp-toast-text">
        <p className="mlp-toast-title">{toast.title}</p>
        {toast.body !== undefined && <p className="mlp-toast-body">{toast.body}</p>}
      </div>
      <button
        type="button"
        className="mlp-icon-btn mlp-toast-close"
        data-testid="toast-dismiss"
        onClick={() => onDismiss(toast.id)}
      >
        <IconClose size={14} />
        {/* Just "Dismiss". Naming it after the message it closes would read
            better in an element list, but the button lives *inside* the live
            region, so the title would be announced a second time as part of
            the button — every toast read twice. The message directly above it
            is the context. */}
        <span className="mlp-visually-hidden">Dismiss</span>
      </button>
    </div>
  );
}

/**
 * Both regions are rendered unconditionally, even with nothing in them: a live
 * region has to be in the accessibility tree *before* content lands in it, or
 * the insertion is not treated as an update.
 *
 * Errors sit above the rest of the stack. They are the ones that stay, so
 * anchoring them to the top of the column keeps them from being pushed around
 * by successes arriving and expiring underneath.
 */
function ToastRegion({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}) {
  const errors = toasts.filter((t) => t.tone === "error");
  const rest = toasts.filter((t) => t.tone !== "error");

  return (
    <div className="mlp-toast-region" data-testid="toast-region">
      <div
        role="alert"
        aria-live="assertive"
        // `role="alert"` and `role="status"` both imply `aria-atomic="true"`,
        // which on a *container* means every arrival re-announces the whole
        // stack: post two successes and the first is read again. Overridden
        // explicitly so only the toast that changed is announced.
        aria-atomic="false"
        className="mlp-toast-stack"
        // Test ids as well as roles: `role="alert"` and `role="status"` are also
        // what `ErrorState` and `EmptyState` carry, so a test that reaches for
        // the role inside a real panel gets several matches and cannot say
        // which region a message landed in.
        data-testid="toast-assertive"
      >
        {errors.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
        ))}
      </div>
      <div
        role="status"
        aria-live="polite"
        aria-atomic="false"
        className="mlp-toast-stack"
        data-testid="toast-polite"
      >
        {rest.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
        ))}
      </div>
    </div>
  );
}
