import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, type TaskClient } from "../api/client";
import type { DisplayBlock, InputField, Task, TemplateSchema } from "../api/types";
import { GuidelinesPanel } from "../components/GuidelinesPanel";
import { HotkeyOverlay } from "../components/HotkeyOverlay";
import { SessionStats, type SessionState } from "../components/SessionStats";
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
  guidelines = "",
  sessionGoal = 25,
  initialAutoSubmit = false,
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

  return (
    <div className="mlp-app" data-theme={theme} data-testid="annotate-root">
      <div className="mlp-annotate" style={{ maxWidth }}>
        <div className="mlp-topbar">
          <SessionStats session={session} reputation={reputation} />
          <div className="mlp-actions">
            <label
              className="mlp-autosubmit"
              title="Submit as soon as a single-choice answer is picked"
              data-testid="toggle-autosubmit"
            >
              <input
                type="checkbox"
                checked={autoSubmit}
                onChange={toggleAutoSubmit}
              />
              Auto-submit
            </label>
            <button
              type="button"
              className="mlp-btn"
              onClick={() => setOverlayOpen((o) => !o)}
              data-testid="btn-help"
              aria-label="Keyboard shortcuts"
            >
              ?
            </button>
            <button
              type="button"
              className="mlp-btn"
              onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
              data-testid="btn-theme"
            >
              {theme === "light" ? "Dark" : "Light"}
            </button>
            <button
              type="button"
              className="mlp-btn"
              onClick={() => void doSkip()}
              disabled={!task}
              data-testid="btn-skip"
            >
              Skip (s)
            </button>
            <button
              type="button"
              className="mlp-btn mlp-btn-primary"
              onClick={() => void doSubmit(answers)}
              disabled={!task || !complete}
              data-testid="btn-submit"
            >
              Submit ⏎
            </button>
          </div>
        </div>

        <div
          className="mlp-progress"
          data-testid="session-progress"
          role="progressbar"
          aria-label="Session progress"
          aria-valuemin={0}
          aria-valuemax={sessionGoal}
          aria-valuenow={Math.min(session.submitted, sessionGoal)}
        >
          <span
            style={{
              width: `${Math.min(100, sessionGoal > 0 ? (session.submitted / sessionGoal) * 100 : 0)}%`,
            }}
          />
        </div>

        <GuidelinesPanel
          markdown={guidelines}
          open={guidelinesOpen}
          onToggle={() => setGuidelinesOpen((o) => !o)}
        />

        {error ? (
          <div className="mlp-card" style={{ borderColor: "var(--danger)" }} data-testid="error">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="mlp-card" data-testid="loading">
            Loading…
          </div>
        ) : paused ? (
          <div
            className="mlp-card"
            style={{ borderColor: "var(--danger)" }}
            data-testid="paused"
            role="status"
          >
            <strong>Paused — no tasks available.</strong>
            <p className="mlp-muted" data-testid="paused-reason">
              {paused}
            </p>
            <p className="mlp-muted">Contact a project admin to have your access restored.</p>
          </div>
        ) : done ? (
          <div className="mlp-card" data-testid="empty-queue">
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
          />
        ) : null}
      </div>

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
}: {
  schema: TemplateSchema;
  task: Task;
  answers: Answers;
  onChange: (id: string, raw: unknown) => void;
  assignment: ReturnType<typeof assignHotkeys>;
  canSubmit: boolean;
  onSubmit: () => void;
  onSkip: () => void;
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
      <div className="mlp-rail-actions">
        <button
          type="button"
          className="mlp-btn"
          onClick={onSkip}
          data-testid="btn-skip-rail"
        >
          Skip (s)
        </button>
        <button
          type="button"
          className="mlp-btn mlp-btn-primary"
          onClick={onSubmit}
          disabled={!canSubmit}
          data-testid="btn-submit-rail"
        >
          Submit ⏎
        </button>
      </div>
    </div>
  );

  if (layout.arrangement === "split") {
    const ratio = layout.ratio ?? [1, 1];
    return (
      <div
        className="mlp-layout-split"
        style={{ gridTemplateColumns: `${ratio[0]}fr ${ratio[1]}fr` }}
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
          style={{ gridTemplateColumns: ratio.map((r) => `${r}fr`).join(" ") }}
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
