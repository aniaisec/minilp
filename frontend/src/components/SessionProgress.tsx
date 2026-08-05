// Session progress as segments rather than a continuous fill (§ UX plan, phase 4).
//
// The old bar was a 6px sliver that grew by four percent per label. At that
// resolution a labeler could not tell whether the last submit had registered,
// which is exactly the question the bar exists to answer. Discrete segments make
// each label a visible event, and the numeric readout beside them removes the
// counting.
//
// Two things are deliberate:
//
// **The segment count is capped.** A session goal of 200 would be 200 hairlines,
// which is a texture, not a readout. Above the cap the segments each stand for
// several labels; the `aria-valuenow`, the `aria-valuetext` and the readout all
// stay exact, so the approximation is only ever in the graphic.
//
// **The graphic is `aria-hidden` and the element is a progressbar.** Announcing
// twelve empty spans is worse than announcing nothing; the role plus
// `aria-valuetext` says "3 of 12 labeled this session" in one utterance.

const MAX_SEGMENTS = 24;

export function SessionProgress({ done, goal }: { done: number; goal: number }) {
  const safeGoal = Math.max(0, Math.floor(goal));
  const capped = Math.max(0, Math.min(done, safeGoal));

  if (safeGoal === 0) return null;

  const segments = Math.min(safeGoal, MAX_SEGMENTS);
  // Ceil so the first label of a session lights the first segment: "nothing has
  // happened yet" and "one label in" must not look the same.
  const filled = Math.ceil((capped / safeGoal) * segments);

  return (
    <div
      className="mlp-seg-progress"
      data-testid="session-progress"
      role="progressbar"
      aria-label="Session progress"
      aria-valuemin={0}
      aria-valuemax={safeGoal}
      aria-valuenow={capped}
      aria-valuetext={`${capped} of ${safeGoal} labeled this session`}
    >
      <span className="mlp-seg-track" aria-hidden="true">
        {Array.from({ length: segments }, (_, i) => (
          <span key={i} className={i < filled ? "mlp-seg mlp-seg-on" : "mlp-seg"} />
        ))}
      </span>
      <span className="mlp-seg-readout" aria-hidden="true">
        {capped}/{safeGoal}
      </span>
    </div>
  );
}
