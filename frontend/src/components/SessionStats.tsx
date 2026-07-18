// Per-session throughput readout (§2.3/§11 session stats).
export interface SessionState {
  submitted: number;
  skipped: number;
  startedAt: number; // epoch ms
}

export function SessionStats({ session }: { session: SessionState }) {
  const mins = Math.max((Date.now() - session.startedAt) / 60000, 1 / 60);
  const perHour = Math.round((session.submitted / mins) * 60);
  return (
    <div className="mlp-stats" data-testid="session-stats">
      <span data-testid="stat-submitted">Labeled: {session.submitted}</span>
      <span data-testid="stat-skipped">Skipped: {session.skipped}</span>
      <span data-testid="stat-rate">{session.submitted > 0 ? `${perHour}/hr` : "—/hr"}</span>
    </div>
  );
}
