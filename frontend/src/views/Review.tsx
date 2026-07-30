// Human review queue (M8, §7.2) — throughput-optimized like the annotation view.
//
// The design constraint is the same one the annotation view has: a reviewer will
// see hundreds of these, so every decision must be one key press and the screen
// must contain everything needed to make it. Concretely:
//
// - `a` approves the merged proposal, `o` opens the override editor, `n`/`p`
//   move through the queue. Nothing here requires the mouse.
// - Each vote shows *who* voted, at what weight, in which variant, with the
//   judge's reasoning trace inline. §7.2 asks for exactly this, and a reviewer
//   who has to open another view to see why the ensemble proposed something will
//   simply stop looking.
// - Deciding advances to the next item, because stopping to admire a decision is
//   not a workflow.
//
// Answers render through the same widget registry the annotation view uses, so a
// reviewer overriding a ranking gets the ranking widget rather than a JSON box.

import { useCallback, useEffect, useMemo, useState } from "react";

import type { MiniLpClient } from "../api/client";
import type { InputField, ReviewItem, TemplateSchema } from "../api/types";
import { eventToken, isTypingTarget } from "../hotkeys/event";
import { canonicalize } from "../render/canonical";
import { isComplete } from "../render/complete";
import { DISPLAY_WIDGETS, INPUT_WIDGETS } from "../widgets/registry";

function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}

function describe(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.map(describe).join(", ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${describe(v)}`)
      .join(" · ");
  }
  return String(value);
}

/** The payload, rendered with the template's own display blocks where possible. */
function UnitPreview({ item }: { item: ReviewItem }) {
  const schema = item.template?.schema;
  if (!schema) {
    return (
      <pre className="mlp-json" data-testid="review-payload-json">
        {JSON.stringify(item.payload, null, 2)}
      </pre>
    );
  }
  return (
    <div className="mlp-review-preview">
      {(schema.display ?? []).map((block, i) => {
        const Widget = DISPLAY_WIDGETS[block.type];
        if (!Widget) return null;
        // Variant-free: a reviewer is looking at the unit, not at one rater's
        // presentation of it. Each vote's own variant is shown beside the vote.
        return (
          <Widget key={`${block.type}-${i}`} block={block} payload={item.payload} variant={null} />
        );
      })}
    </div>
  );
}

export interface ReviewProps {
  client: MiniLpClient;
  projectId?: number;
  /** Rendered above the queue when the reviewer arrived from home. */
  exit?: React.ReactNode;
}

export function Review({ client, projectId, exit }: ReviewProps) {
  const [queue, setQueue] = useState<ReviewItem[] | null>(null);
  const [depth, setDepth] = useState(0);
  const [index, setIndex] = useState(0);
  const [detail, setDetail] = useState<ReviewItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [overriding, setOverriding] = useState(false);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [comment, setComment] = useState("");
  const [decided, setDecided] = useState(0);

  const load = useCallback(async () => {
    setError(null);
    try {
      const q = await client.reviewQueue(projectId);
      setQueue(q.items);
      setDepth(q.depth);
      setIndex((i) => (q.items.length === 0 ? 0 : Math.min(i, q.items.length - 1)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [client, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const current = queue && queue.length > index ? queue[index] : null;

  // The list item carries the proposal; the detail fetch adds the template, which
  // is what lets the override editor render real widgets instead of raw JSON.
  useEffect(() => {
    let live = true;
    setDetail(null);
    setOverriding(false);
    setAnswers({});
    setComment("");
    if (!current) return;
    client
      .reviewItem(current.unit_id)
      .then((d) => live && setDetail(d))
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [client, current?.unit_id]);

  const item = detail ?? current;
  const schema: TemplateSchema | undefined = detail?.template?.schema;
  const inputs: InputField[] = schema?.inputs ?? [];
  const overrideComplete = schema ? isComplete(schema, answers) : Object.keys(answers).length > 0;

  const advance = useCallback(() => {
    setQueue((q) => {
      if (!q || !current) return q;
      const next = q.filter((i) => i.unit_id !== current.unit_id);
      setIndex((old) => Math.min(old, Math.max(0, next.length - 1)));
      return next;
    });
  }, [current]);

  const submitDecision = useCallback(
    async (decision: "approve" | "override") => {
      if (!current || busy) return;
      setBusy(true);
      setError(null);
      try {
        const value =
          decision === "override"
            ? schema
              ? canonicalize(schema, answers, null)
              : answers
            : undefined;
        const outcome = await client.decideReview(current.unit_id, {
          decision,
          value,
          comment: comment || undefined,
        });
        setDepth(outcome.queue_depth);
        setDecided((n) => n + 1);
        advance();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [client, current, busy, schema, answers, comment, advance],
  );

  // Keyboard dispatcher — the same shape as the annotation view's (§2.4).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const token = eventToken(e);
      if (token === "a" && current && !overriding) {
        e.preventDefault();
        void submitDecision("approve");
      } else if (token === "o" && current) {
        e.preventDefault();
        setOverriding((v) => !v);
      } else if (token === "n") {
        e.preventDefault();
        setIndex((i) => (queue && i < queue.length - 1 ? i + 1 : i));
      } else if (token === "p") {
        e.preventDefault();
        setIndex((i) => Math.max(0, i - 1));
      } else if (token === "enter" && overriding && overrideComplete) {
        e.preventDefault();
        void submitDecision("override");
      } else if (token === "escape" && overriding) {
        e.preventDefault();
        setOverriding(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, overriding, overrideComplete, queue, submitDecision]);

  const votes = useMemo(() => item?.proposal?.votes ?? [], [item]);

  return (
    <div className="mlp-annotate" style={{ maxWidth: "var(--content-xl)", margin: "0 auto" }}>
      <div className="mlp-topbar">
        <div className="mlp-topbar-left">
          {exit}
          <span className="mlp-muted" data-testid="review-depth">
            Review queue · {depth} waiting
            {decided > 0 ? ` · ${decided} decided this session` : ""}
          </span>
        </div>
        <div className="mlp-actions">
          <button
            type="button"
            className="mlp-btn"
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
            disabled={index === 0}
            data-testid="review-prev"
          >
            Prev (p)
          </button>
          <button
            type="button"
            className="mlp-btn"
            onClick={() => setIndex((i) => (queue && i < queue.length - 1 ? i + 1 : i))}
            disabled={!queue || index >= queue.length - 1}
            data-testid="review-next"
          >
            Next (n)
          </button>
          <button
            type="button"
            className="mlp-btn"
            onClick={() => setOverriding((v) => !v)}
            disabled={!current}
            data-testid="review-override-toggle"
          >
            Override (o)
          </button>
          <button
            type="button"
            className="mlp-btn mlp-btn-primary"
            onClick={() => void submitDecision("approve")}
            disabled={!current || busy || !item?.proposal}
            data-testid="review-approve"
          >
            Approve (a)
          </button>
        </div>
      </div>

      {error && (
        <div
          className="mlp-card"
          style={{ borderColor: "var(--danger)" }}
          data-testid="review-error"
        >
          {error}
        </div>
      )}

      {!queue && !error && <div className="mlp-card">Loading queue…</div>}

      {queue && queue.length === 0 && (
        <div className="mlp-card mlp-muted" data-testid="review-empty">
          <strong>Nothing to review.</strong>
          <p style={{ margin: "6px 0 0" }}>
            Units arrive here when the routing pipeline cannot finalize them on its own —
            low consensus, high disagreement, or a policy that always asks a human.
          </p>
        </div>
      )}

      {item && (
        <div className="mlp-review-grid">
          <div className="mlp-card" data-testid="review-unit">
            <div className="mlp-review-head">
              <strong>Unit #{item.unit_id}</strong>
              <span className="mlp-muted">
                {item.project_name} · priority {item.priority}
                {item.is_gold ? " · gold" : ""}
              </span>
            </div>
            {item.escalation_reason && (
              <div className="mlp-muted" data-testid="review-reason" style={{ fontSize: 13 }}>
                {item.escalation_reason}
                {item.failed_keys.length > 0 ? ` (${item.failed_keys.join(", ")})` : ""}
              </div>
            )}
            <UnitPreview item={item} />
          </div>

          <div className="mlp-card" data-testid="review-proposal">
            {item.proposal ? (
              <>
                <div className="mlp-review-head">
                  <strong>Proposed answer</strong>
                  <span className="mlp-muted">
                    {item.proposal.method} · consensus {pct(item.proposal.confidence)} · entropy{" "}
                    {item.proposal.entropy.toFixed(2)}
                  </span>
                </div>
                <div className="mlp-review-proposed" data-testid="review-proposed-value">
                  {describe(item.proposal.value)}
                </div>

                <div className="mlp-dist-title">Votes</div>
                <table className="mlp-table" data-testid="review-votes">
                  <thead>
                    <tr>
                      <th>Rater</th>
                      <th>Answer</th>
                      <th>Weight</th>
                      <th>Conf.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {votes.map((v) => (
                      <tr key={v.label_id} data-testid={`review-vote-${v.annotator_id}`}>
                        <td>
                          <div>{v.judge ?? v.name ?? `#${v.annotator_id}`}</div>
                          <div className="mlp-muted" style={{ fontSize: 12 }}>
                            {v.kind}
                            {v.variant ? ` · ${describe(v.variant)}` : ""}
                          </div>
                        </td>
                        <td>{describe(v.value)}</td>
                        <td>{v.weight.toFixed(2)}</td>
                        <td>{v.confidence === null ? "—" : v.confidence.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {votes.some((v) => v.reasoning) && (
                  <div className="mlp-review-traces" data-testid="review-traces">
                    <div className="mlp-dist-title">Reasoning</div>
                    {votes
                      .filter((v) => v.reasoning)
                      .map((v) => (
                        <div key={`trace-${v.label_id}`} className="mlp-review-trace">
                          <span className="mlp-muted">{v.judge ?? v.name}: </span>
                          {v.reasoning}
                        </div>
                      ))}
                  </div>
                )}
              </>
            ) : (
              <div className="mlp-muted" data-testid="review-no-proposal">
                No labels to merge — this unit can only be decided by overriding.
              </div>
            )}

            {overriding && (
              <div className="mlp-review-override" data-testid="review-override">
                <div className="mlp-dist-title">Your answer</div>
                {inputs.length === 0 && (
                  <div className="mlp-muted" style={{ fontSize: 13 }}>
                    Loading the template…
                  </div>
                )}
                {inputs.map((input) => {
                  const Widget = INPUT_WIDGETS[input.type];
                  if (!Widget) return null;
                  return (
                    <Widget
                      key={input.id}
                      input={input}
                      value={answers[input.id]}
                      hotkeys={{ options: {}, other: null }}
                      onChange={(raw: unknown) =>
                        setAnswers((a) => ({ ...a, [input.id]: raw }))
                      }
                    />
                  );
                })}
                <input
                  className="mlp-input"
                  type="text"
                  placeholder="Why? (stored with the decision)"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  data-testid="review-comment"
                />
                <div className="mlp-rail-actions">
                  <button
                    type="button"
                    className="mlp-btn"
                    onClick={() => setOverriding(false)}
                  >
                    Cancel (esc)
                  </button>
                  <button
                    type="button"
                    className="mlp-btn mlp-btn-primary"
                    disabled={!overrideComplete || busy}
                    onClick={() => void submitDecision("override")}
                    data-testid="review-override-submit"
                  >
                    Save override ⏎
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
