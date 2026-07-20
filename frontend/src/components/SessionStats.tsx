// Per-session throughput readout (§2.3/§11 session stats), plus the annotator's
// live reputation (§6.2) once the quality subsystem has something to say.
//
// Reputation is shown as a plain percentage with no pass/fail styling below the
// "good" band: the number is a rolling quality signal, not a grade, and dressing
// a 0.82 in red would push annotators toward second-guessing correct answers.
// Only an actual pause (a state change they need to act on) is surfaced loudly,
// and that is the Annotate view's job, not this bar's.

export interface SessionState {
  submitted: number;
  skipped: number;
  startedAt: number; // epoch ms
}

export function SessionStats({
  session,
  reputation = null,
}: {
  session: SessionState;
  reputation?: number | null;
}) {
  const mins = Math.max((Date.now() - session.startedAt) / 60000, 1 / 60);
  const perHour = Math.round((session.submitted / mins) * 60);
  return (
    <div className="mlp-stats" data-testid="session-stats">
      <span data-testid="stat-submitted">Labeled: {session.submitted}</span>
      <span data-testid="stat-skipped">Skipped: {session.skipped}</span>
      <span data-testid="stat-rate">{session.submitted > 0 ? `${perHour}/hr` : "—/hr"}</span>
      {reputation === null ? null : (
        <span data-testid="stat-reputation" title="Rolling quality score (§6.2)">
          Quality: {Math.round(reputation * 100)}%
        </span>
      )}
    </div>
  );
}
