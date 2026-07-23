// Presentational helpers shared across the admin views (§11). Pure and unit-
// tested so the number-formatting the dashboard leans on can't silently drift.

import type { Estimate } from "../../api/types";

/** A 0..1 proportion as a percentage string, e.g. 0.667 → "66.7%". */
export function pct(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

/** A duration in hours rendered compactly: 0.5 → "30m", 5 → "5.0h", 50 → "2.1d". */
export function eta(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return "—";
  if (!Number.isFinite(hours)) return "—";
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 48) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

/** A point estimate with its CI: 0.75 [0.60–0.86]. */
export function ci(e: Estimate | null | undefined): string {
  if (!e) return "—";
  return `${e.estimate.toFixed(2)} [${e.ci_low.toFixed(2)}–${e.ci_high.toFixed(2)}]`;
}

/** Histogram entries sorted by count desc, ready to render as bars. */
export function ranked(hist: Record<string, number>): [string, number][] {
  return Object.entries(hist).sort((a, b) => b[1] - a[1]);
}

/** Sum of a histogram's counts (denominator for share bars). */
export function total(hist: Record<string, number>): number {
  return Object.values(hist).reduce((a, b) => a + b, 0);
}
