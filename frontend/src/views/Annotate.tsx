import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { ApiError, type TaskClient } from "../api/client";
import type { DisplayBlock, InputField, Task, TemplateSchema } from "../api/types";
import { ExitToHome } from "../components/ExitToHome";
import { GuidelinesPanel } from "../components/GuidelinesPanel";
import { HotkeyOverlay } from "../components/HotkeyOverlay";
import { IconHelp, IconMoon, IconSun } from "../components/icons";
import { SessionProgress } from "../components/SessionProgress";
import { SessionStats, type SessionState } from "../components/SessionStats";
import { TaskSkeleton } from "../components/TaskSkeleton";
import { assignHotkeys } from "../hotkeys/assign";
import { eventToken, isTypingTarget } from "../hotkeys/event";
import { canonicalize } from "../render/canonical";
import { autoSubmitInputId, isComplete } from "../render/complete";
import { applyOption, isOtherRaw, resolveOptions, toggleOther } from "../render/options";
import { variantString } from "../render/resolve";
import { DISPLAY_WIDGETS, INPUT_WIDGETS } from "../widgets/registry";

const WIDTHS: Record<string, string> = {
  md: "var(--content-md)",
  lg: "var(--content-lg)",
  xl: "var(--content-xl)",
  full: "var(--content-full)",
};

export interface AnnotateProps {
  client: TaskClient;
  annotatorId: number;
  projectId: number;
  schema: TemplateSchema;
  /**
   * Names the screen (§ UX plan, phase 4): it is the `<h1>` in the task bar and
   * the first segment of the document title. Falls back to the template's name,
   * which is at least a description of the work — never to "Project #3", which
   * is a description of the database.
   */
  projectName?: string;
  guidelines?: string;
  /**
   * Labels to aim for this session; drives the progress bar (§11). True
   * project-completion progress arrives with the M5 progress endpoint — until
   * then the bar tracks session momentum rather than project state.
   */
  sessionGoal?: number;
  /**
   * Opt-in auto-submit: when on, a single-required-choice template submits the
   * instant an option is picked (the pre-M5 default, now a speed optimization the
   * annotator chooses). Off by default — you select, adjust if needed, then click
   * Submit (or press Enter). Persisted across sessions in localStorage; the prop
   * seeds tests and the very first render.
   */
  initialAutoSubmit?: boolean;
  /**
   * Where the exit control goes (M8, §11). Omitted, no exit control is rendered
   * — which is what the admin "try this project" preview wants, since it was not
   * reached from home and has nowhere of its own to go back to.
   */
  homeHref?: string;
  /**
   * True when this view is mounted *inside* another page — the live previews in
   * the template gallery and the visual builder both do it.
   *
   * A page can only have one of several things this view owns: one `<h1>`, one
   * element with `id="main"`, one skip link, one top-edge mode bar. Rendered
   * embedded, all four would be duplicates sitting inside the admin surface's
   * own `<main>`, which is a worse document than the one that existed before
   * this phase. So the chrome that only makes sense for a whole page is dropped
   * and the task bar renders as preview furniture.
   *
   * `data-mode="label"` is deliberately *kept*: a preview of the labeling
   * surface should look like the labeling surface, teal accent and all.
   */
  embedded?: boolean;
}

const AUTO_SUBMIT_KEY = "mlp.autoSubmit";

function readAutoSubmitPref(fallback: boolean): boolean {
  try {
    const v = window.localStorage.getItem(AUTO_SUBMIT_KEY);
    return v === null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}

type Answers = Record<string, unknown>;

export function Annotate({
  client,
  annotatorId,
  projectId,
  schema,
  projectName,
  guidelines = "",
  sessionGoal = 25,
  initialAutoSubmit = false,
  homeHref,
  embedded = false,
}: AnnotateProps) {
  const [task, setTask] = useState<Task | null>(null);
  const [answers, setAnswers] = useState<Answers>({});
  const [autoSubmit, setAutoSubmit] = useState<boolean>(() =>
    readAutoSubmitPref(initialAutoSubmit),
  );
  const [loading, setLoading] = useState(true);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [guidelinesOpen, setGuidelinesOpen] = useState(true);
  const [overlayOpen, setOverlayOpen] = useState(false);
  // Quality state (M4, §6). `paused` holds the reason the backend gave; while it
  // is set the annotator has no queue, so the view stops asking for tasks.
  const [paused, setPaused] = useState<string | null>(null);
  const [reputation, setReputation] = useState<number | null>(null);
  const [session, setSession] = useState<SessionState>({
    submitted: 0,
    skipped: 0,
    startedAt: Date.now(),
  });

  const undoStack = useRef<Answers[]>([]);
  const tasksSeen = useRef(0);
  // Time on the current task, reported so the backend can raise a speed flag
  // (§6.2). Reset every time a task is rendered, not when the answer changes.
  const taskShownAt = useRef<number>(Date.now());
  const mainRef = useRef<HTMLElement | null>(null);

  const title = projectName || schema.name;
  const assignment = useMemo(() => assignHotkeys(schema.inputs), [schema]);
  const positionalVariant = useMemo(
    () => variantString(schema, task?.variant),
    [schema, task],
  );
  const autoId = useMemo(() => autoSubmitInputId(schema), [schema]);
  const complete = isComplete(schema, answers);

  const loadNext = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await client.nextTask(annotatorId, projectId);
      undoStack.current = [];
      setAnswers({});
      if (next === null) {
        setTask(null);
        setDone(true);
      } else {
        setTask(next);
        setDone(false);
        setGuidelinesOpen(tasksSeen.current === 0);
        tasksSeen.current += 1;
        taskShownAt.current = Date.now();
      }
    } catch (e) {
      // 403 from /tasks/next is the quality gate, not a failure: the annotator is
      // paused or below the project's min_reputation (§6.1, §6.2). Showing them
      // the reason beats an empty queue that looks like "no work today".
      if (e instanceof ApiError && e.status === 403) {
        setPaused(e.message);
        setTask(null);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setLoading(false);
    }
  }, [client, annotatorId, projectId]);

  useEffect(() => {
    void loadNext();
  }, [loadNext]);

  // Theme lives on <html> so body/page chrome pick up the tokens too — setting it
  // only on an inner element would leave the page background unthemed.
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.getAttribute("data-theme");
    root.setAttribute("data-theme", theme);
    return () => {
      if (previous === null) root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", previous);
    };
  }, [theme]);

  // Announce the surface through the document title (§ UX plan, mode identity),
  // so a screen-reader user knows they are labeling and not administering
  // without exploring the page to work it out. Same shape as the admin shell.
  //
  // Not when embedded: a preview inside the template gallery would rename the
  // admin's tab to the template it happens to be previewing.
  useEffect(() => {
    if (embedded) return;
    document.title = `${title} · Labeling · MiniLP`;
  }, [title, embedded]);

  const doSubmit = useCallback(
    async (raw: Answers) => {
      if (!task || !isComplete(schema, raw)) return;
      setError(null);
      try {
        // `value` is advisory since M4 — the server recanonicalizes — but sending
        // it keeps the client honest and lets the two be compared.
        const value = canonicalize(schema, raw, positionalVariant);
        const label = await client.submit(task.slot_id, annotatorId, {
          raw,
          value,
          latency_ms: Math.max(0, Math.round(Date.now() - taskShownAt.current)),
        });
        setSession((s) => ({ ...s, submitted: s.submitted + 1 }));
        const quality = label?.quality;
        if (quality) {
          if (quality.reputation !== null) setReputation(quality.reputation);
          if (quality.paused) {
            // The backend has already voided their recent work; don't ask for
            // another task, just tell them and stop.
            setPaused(
              quality.labels_voided > 0
                ? `Your account has been paused for quality review; ${quality.labels_voided} recent labels were returned to the queue.`
                : "Your account has been paused for quality review.",
            );
            setTask(null);
            return;
          }
        }
        await loadNext();
      } catch (e) {
        if (e instanceof ApiError && e.status === 403) {
          setPaused(e.message);
          setTask(null);
        } else {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    },
    [task, schema, positionalVariant, client, annotatorId, loadNext],
  );

  const doSkip = useCallback(async () => {
    if (!task) return;
    try {
      await client.skip(task.slot_id, annotatorId);
      setSession((s) => ({ ...s, skipped: s.skipped + 1 }));
      await loadNext();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [task, client, annotatorId, loadNext]);

  // Central answer mutation — mouse and keyboard both route here so they can
  // never diverge. Fires single-input auto-submit on a discrete option (§2.4).
  const handleChange = useCallback(
    (inputId: string, raw: unknown) => {
      undoStack.current.push(answers);
      const next = { ...answers, [inputId]: raw };
      setAnswers(next);
      // Auto-submit is opt-in (§ user request): only fire when the annotator has
      // switched it on. Never on the "Other…" escape hatch — they still need to
      // type the free-text label first.
      if (autoSubmit && autoId === inputId && !isOtherRaw(raw) && isComplete(schema, next)) {
        void doSubmit(next);
      }
    },
    [answers, autoSubmit, autoId, schema, doSubmit],
  );

  const toggleAutoSubmit = useCallback(() => {
    setAutoSubmit((on) => {
      const nextOn = !on;
      try {
        window.localStorage.setItem(AUTO_SUBMIT_KEY, nextOn ? "1" : "0");
      } catch {
        /* storage unavailable — keep it session-only */
      }
      return nextOn;
    });
  }, []);

  const undo = useCallback(() => {
    setAnswers((prev) => {
      const last = undoStack.current.pop();
      return last ?? prev;
    });
  }, []);

  // Keyboard dispatcher (§2.4). Re-registered as state changes; cheap.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const token = eventToken(e);
      const typing = isTypingTarget(e.target);

      if (token === "escape") {
        if (overlayOpen) {
          setOverlayOpen(false);
          e.preventDefault();
        }
        return;
      }

      // While the dialog is open, only the key that closes it does anything.
      // A hotkey that fires behind a modal answers a question the person cannot
      // see, and the dialog's own focus trap cannot stop a window-level
      // listener — it has to decline (§ UX plan, "hotkeys do not fight
      // assistive technology").
      if (overlayOpen) {
        if (token === "?") {
          e.preventDefault();
          setOverlayOpen(false);
        }
        return;
      }

      if (token === "enter") {
        const inTextarea =
          e.target instanceof HTMLElement && e.target.tagName.toLowerCase() === "textarea";
        if (inTextarea) return; // newline
        if (complete) {
          e.preventDefault();
          void doSubmit(answers);
        }
        return;
      }
      if (typing) return; // let letters/digits flow into text fields

      switch (token) {
        case "s":
          e.preventDefault();
          void doSkip();
          return;
        case "g":
          e.preventDefault();
          setGuidelinesOpen((o) => !o);
          return;
        case "d":
          e.preventDefault();
          setTheme((t) => (t === "light" ? "dark" : "light"));
          return;
        case "u":
          e.preventDefault();
          undo();
          return;
        case "?":
          e.preventDefault();
          setOverlayOpen((o) => !o);
          return;
      }

      // Option hotkeys.
      for (const input of schema.inputs) {
        const hk = assignment.byInput[input.id];
        if (!hk) continue;
        if (hk.other && token === hk.other) {
          e.preventDefault();
          handleChange(input.id, toggleOther(input, answers[input.id]));
          return;
        }
        for (const opt of resolveOptions(input, hk)) {
          if (opt.key && token === opt.key) {
            e.preventDefault();
            handleChange(input.id, applyOption(input, answers[input.id], opt));
            return;
          }
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    schema,
    assignment,
    answers,
    complete,
    overlayOpen,
    doSubmit,
    doSkip,
    undo,
    handleChange,
  ]);

  const layout = schema.layout ?? { arrangement: "stack" };
  const maxWidth = WIDTHS[layout.width ?? "lg"] ?? WIDTHS.lg;

  // Landmarks and the page heading belong to a page. Embedded in the admin
  // surface's own `<main>`, they would be duplicates of things that already
  // exist there, so the same markup renders as plain elements instead.
  const Bar = embedded ? "div" : "header";
  const Title = embedded ? "p" : "h1";
  const Body = embedded ? "div" : "main";

  return (
    <div
      className="mlp-app mlp-label-shell"
      data-theme={theme}
      // Teal, not blue. The accent triple is re-pointed by one attribute (see
      // the mode block in theme.css); `data-theme` stays independent so the two
      // compose. Admin actions change configuration, labeling produces data —
      // a person should never be unsure which of those they are doing.
      data-mode="label"
      data-embedded={embedded ? "true" : undefined}
      data-testid="annotate-root"
    >
      {/* Peripheral-vision mode marker. Decorative — the chip in the task bar is
          what actually names the mode, because blue against teal is a plausible
          confusion under deuteranopia. */}
      {!embedded && <div className="mlp-mode-bar" aria-hidden="true" />}

      {/* First tab stop. `preventDefault` because the labeler surface routes on
          the query string: letting "#main" land in the address bar would look
          like a route change to the admin shell's hash listener. */}
      {!embedded && (
        <a
          className="mlp-skip-link mlp-visually-hidden-focusable"
          href="#main"
          data-testid="skip-link"
          onClick={(e) => {
            e.preventDefault();
            const main = mainRef.current;
            if (main) {
              main.focus();
              // Optional-called: jsdom has no layout, so no `scrollIntoView`,
              // and focus is the part that has to work anyway.
              main.scrollIntoView?.();
            }
          }}
        >
          Skip to content
        </a>
      )}

      {/* The task bar. Everything here is either "where am I" or "how is the
          session going"; the controls that act on *this unit* live at the end
          of the input rail, where the answer is. Mixing the two in one flex row
          is what made the old topbar unreadable at a glance. */}
      <Bar className="mlp-taskbar" data-testid="taskbar">
        <div className="mlp-taskbar-id">
          {homeHref ? (
            <ExitToHome
              href={homeHref}
              // Leaving releases the held lease through the same `skip` path
              // the `s` key uses, so the slot reopens now — variant retained
              // (§2.7) — instead of sitting leased until it expires.
              onLeave={async () => {
                if (task) await client.skip(task.slot_id, annotatorId);
              }}
              dirty={Object.keys(answers).length > 0 && !!task}
              // `x` must not fire behind the shortcuts dialog: quitting the task
              // is the one action here you cannot undo.
              hotkey={!overlayOpen}
            />
          ) : null}
          <Title className="mlp-taskbar-title" title={title}>
            {title}
          </Title>
          <span className="mlp-mode-chip" data-testid="mode-chip">
            Labeling
          </span>
        </div>

        <SessionProgress done={session.submitted} goal={sessionGoal} />

        <div className="mlp-taskbar-tools">
          <SessionStats session={session} reputation={reputation} />
          <button
            type="button"
            className="mlp-icon-btn"
            onClick={() => setOverlayOpen((o) => !o)}
            aria-expanded={overlayOpen}
            data-testid="btn-help"
          >
            <IconHelp />
            <span className="mlp-visually-hidden">Keyboard shortcuts</span>
          </button>
          <button
            type="button"
            className="mlp-icon-btn"
            onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
            data-testid="theme-toggle"
          >
            {theme === "light" ? <IconMoon /> : <IconSun />}
            <span className="mlp-visually-hidden">
              Switch to {theme === "light" ? "dark" : "light"} theme
            </span>
          </button>
        </div>
      </Bar>

      <Body
        className="mlp-annotate"
        id={embedded ? undefined : "main"}
        // A callback ref, not the ref object: `Body` is `"main" | "div"`, and a
        // ref object has to pick one element type where a callback does not.
        ref={(el: HTMLElement | null) => {
          mainRef.current = el;
        }}
        // -1 so the skip link can move focus here without making <main> a tab
        // stop of its own.
        tabIndex={embedded ? undefined : -1}
        style={{ maxWidth }}
      >
        <GuidelinesPanel
          markdown={guidelines}
          open={guidelinesOpen}
          onToggle={() => setGuidelinesOpen((o) => !o)}
        />

        {error ? (
          <div
            className="mlp-card mlp-card-danger"
            data-testid="error"
            // Assertive: a submit that failed has to interrupt, because the
            // next thing the labeler does otherwise is answer the same unit again.
            role="alert"
          >
            {error}
          </div>
        ) : null}

        {loading ? (
          <TaskSkeleton split={layout.arrangement === "split"} />
        ) : paused ? (
          <div className="mlp-card mlp-card-danger" data-testid="paused" role="status">
            <strong>Paused — no tasks available.</strong>
            <p className="mlp-muted" data-testid="paused-reason">
              {paused}
            </p>
            <p className="mlp-muted">Contact a project admin to have your access restored.</p>
          </div>
        ) : done ? (
          <div className="mlp-card" data-testid="empty-queue" role="status">
            All caught up — no tasks in the queue.
          </div>
        ) : task ? (
          <TaskBody
            schema={schema}
            task={task}
            answers={answers}
            onChange={handleChange}
            assignment={assignment}
            canSubmit={complete}
            onSubmit={() => void doSubmit(answers)}
            onSkip={() => void doSkip()}
            autoSubmit={autoSubmit}
            onToggleAutoSubmit={toggleAutoSubmit}
          />
        ) : null}
      </Body>

      {overlayOpen ? (
        <HotkeyOverlay schema={schema} assignment={assignment} onClose={() => setOverlayOpen(false)} />
      ) : null}
    </div>
  );
}

function TaskBody({
  schema,
  task,
  answers,
  onChange,
  assignment,
  canSubmit,
  onSubmit,
  onSkip,
  autoSubmit,
  onToggleAutoSubmit,
}: {
  schema: TemplateSchema;
  task: Task;
  answers: Answers;
  onChange: (id: string, raw: unknown) => void;
  assignment: ReturnType<typeof assignHotkeys>;
  canSubmit: boolean;
  onSubmit: () => void;
  onSkip: () => void;
  autoSubmit: boolean;
  onToggleAutoSubmit: () => void;
}) {
  const layout = schema.layout ?? { arrangement: "stack" };
  const variant = variantString(schema, task.variant);
  const display = schema.display ?? [];

  const displayRegion = (
    <div className="mlp-display-region" data-testid="display-region">
      {display.map((block, i) => (
        <DisplayBlockView key={i} block={block} payload={task.payload} variant={variant} />
      ))}
    </div>
  );

  // The submit affordance sticks to the bottom of the rail rather than sitting
  // at the natural end of the form. On an image-heavy task the form is taller
  // than the window, and "scroll down to submit" is a scroll on every single
  // unit — which, at a few hundred units a day, is the whole cost of the view.
  const inputRail = (
    <div className="mlp-input-rail" data-testid="input-rail">
      {schema.inputs.map((input) => (
        <InputFieldView
          key={input.id}
          input={input}
          answers={answers}
          onChange={onChange}
          assignment={assignment}
        />
      ))}
      <div className="mlp-rail-footer" data-testid="rail-footer">
        <label
          className="mlp-autosubmit"
          title="Submit as soon as a single-choice answer is picked"
          data-testid="toggle-autosubmit"
        >
          <input type="checkbox" checked={autoSubmit} onChange={onToggleAutoSubmit} />
          Auto-submit
        </label>
        <div className="mlp-rail-footer-actions">
          <button type="button" className="mlp-btn" onClick={onSkip} data-testid="btn-skip">
            Skip
            <kbd className="mlp-badge" data-hotkey="s">
              S
            </kbd>
          </button>
          <button
            type="button"
            className="mlp-btn mlp-btn-primary"
            onClick={onSubmit}
            disabled={!canSubmit}
            data-testid="btn-submit"
          >
            Submit
            <kbd className="mlp-badge" data-hotkey="enter">
              ⏎
            </kbd>
          </button>
        </div>
      </div>
    </div>
  );

  // The template's ratio arrives as a custom property rather than as an inline
  // `grid-template-columns`. An inline declaration beats every stylesheet rule
  // including media queries, so the narrow-window rule that folds these grids
  // into one column could never fire — the ratio has to be data the stylesheet
  // reads, not a declaration that overrides it.
  if (layout.arrangement === "split") {
    const ratio = layout.ratio ?? [1, 1];
    return (
      <div
        className="mlp-layout-split"
        style={{ "--grid-ratio": `${ratio[0]}fr ${ratio[1]}fr` } as CSSProperties}
      >
        {displayRegion}
        {inputRail}
      </div>
    );
  }

  if (layout.arrangement === "columns") {
    const ratio = layout.ratio ?? display.map(() => 1);
    return (
      <div className="mlp-layout-stack">
        <div
          className="mlp-layout-columns"
          style={{ "--grid-ratio": ratio.map((r) => `${r}fr`).join(" ") } as CSSProperties}
        >
          {display.map((block, i) => (
            <DisplayBlockView key={i} block={block} payload={task.payload} variant={variant} />
          ))}
        </div>
        {inputRail}
      </div>
    );
  }

  // stack (default)
  return (
    <div className="mlp-layout-stack">
      {displayRegion}
      {inputRail}
    </div>
  );
}

function DisplayBlockView({
  block,
  payload,
  variant,
}: {
  block: DisplayBlock;
  payload: Record<string, unknown>;
  variant: string | null;
}) {
  const Comp = DISPLAY_WIDGETS[block.type];
  if (!Comp) return <div className="mlp-card mlp-muted">Unknown block: {block.type}</div>;
  return <Comp block={block} payload={payload} variant={variant} />;
}

function InputFieldView({
  input,
  answers,
  onChange,
  assignment,
}: {
  input: InputField;
  answers: Answers;
  onChange: (id: string, raw: unknown) => void;
  assignment: ReturnType<typeof assignHotkeys>;
}) {
  const Comp = INPUT_WIDGETS[input.type];
  if (!Comp) return <div className="mlp-card mlp-muted">Unsupported input: {input.type}</div>;
  const hk = assignment.byInput[input.id] ?? { options: {}, other: null };
  return (
    <Comp
      input={input}
      hotkeys={hk}
      value={answers[input.id]}
      onChange={(raw) => onChange(input.id, raw)}
    />
  );
}
