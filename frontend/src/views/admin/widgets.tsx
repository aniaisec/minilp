// Small presentational building blocks for the admin views (§11). No data
// fetching here — these take already-resolved numbers and draw them.

import type { ReactNode } from "react";

export function StatCard({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mlp-stat">
      <div className="mlp-stat-value">{value}</div>
      <div className="mlp-stat-label">{label}</div>
      {sub !== undefined && <div className="mlp-stat-sub mlp-muted">{sub}</div>}
    </div>
  );
}

/** A single horizontal fill bar, 0..1. */
export function Bar({
  frac,
  color = "var(--accent)",
  label,
}: {
  frac: number;
  color?: string;
  label?: ReactNode;
}) {
  const pctWidth = `${Math.max(0, Math.min(1, frac)) * 100}%`;
  return (
    <div className="mlp-bar">
      <div className="mlp-bar-track">
        <div className="mlp-bar-fill" style={{ width: pctWidth, background: color }} />
      </div>
      {label !== undefined && <div className="mlp-bar-label">{label}</div>}
    </div>
  );
}

/** Two stacked bars sharing a scale — the paired proof of counterbalancing
 *  (variant fill, §2.7). ``denom`` fixes the scale so unequal totals are visible. */
export function PairedBar({
  rows,
  denom,
}: {
  rows: { name: string; filled: number; total: number }[];
  denom: number;
}) {
  const scale = denom || 1;
  return (
    <div className="mlp-paired">
      {rows.map((r) => (
        <div key={r.name} className="mlp-paired-row">
          <span className="mlp-paired-name mlp-mono">{r.name}</span>
          <div className="mlp-bar-track" title={`${r.filled}/${r.total} filled`}>
            <div
              className="mlp-bar-fill"
              style={{ width: `${(r.filled / scale) * 100}%`, background: "var(--ok)" }}
            />
            <div
              className="mlp-bar-fill mlp-bar-ghost"
              style={{ width: `${(r.total / scale) * 100}%` }}
            />
          </div>
          <span className="mlp-paired-num mlp-muted">
            {r.filled}/{r.total}
          </span>
        </div>
      ))}
    </div>
  );
}

export function Pill({ children, tone }: { children: ReactNode; tone?: "ok" | "warn" | "muted" }) {
  const cls = tone ? `mlp-pill mlp-pill-${tone}` : "mlp-pill";
  return <span className={cls}>{children}</span>;
}
