// Progress view (§11): status funnel, per-batch bars, per-variant paired bars
// (counterbalancing proof), per-key consensus rates, throughput + ETA.
//
// Presentational since phase 3 of the UX plan. `ProjectView` owns the fetch,
// because the project header needs the same funnel on every section — fetching
// it here as well would have meant two identical requests on this route.

import { Card, EmptyState } from "../../components/ui";
import type { Progress } from "../../api/types";
import { eta, pct } from "./format";
import { Bar, PairedBar, Pill, StatCard } from "./widgets";

export function ProgressPanel({ data }: { data: Progress }) {
  const f = data.funnel;
  const t = data.throughput;
  const variantDenom = Math.max(1, ...data.variants.values.map((v) => v.total));

  return (
    <div className="mlp-stack-lg">
      <div className="mlp-stat-row">
        <StatCard label="Units" value={f.total} sub={`${f.finalized + f.labeled} done`} />
        <StatCard label="Pending" value={f.pending} />
        <StatCard label="In progress" value={f.in_progress} />
        <StatCard label="Labeled" value={f.labeled} />
        <StatCard
          label="Escalated"
          value={f.escalated}
          sub={f.escalated ? <Pill tone="warn">review</Pill> : "none"}
        />
        <StatCard
          label="Throughput"
          value={`${t.labels_per_hour.toFixed(1)}/hr`}
          sub={`ETA ${eta(t.eta_hours)} · ${t.remaining_slots} slots left`}
        />
      </div>

      <Card headingLevel={3} title="Status funnel">
        {(["pending", "in_progress", "labeled", "finalized"] as const).map((k) => (
          <Bar
            key={k}
            frac={f.total ? f[k] / f.total : 0}
            label={
              <span>
                <span className="mlp-mono">{k}</span> — {f[k]} ({pct(f.total ? f[k] / f.total : 0)})
              </span>
            }
          />
        ))}
      </Card>

      <Card headingLevel={3} title="Per-batch fill">
        {data.batches.length === 0 && (
          <EmptyState title="No batches yet" data-testid="progress-batches-empty">
            Units are added to a project in batches. Add tasks from the Add tasks section and the
            fill rate of each batch appears here.
          </EmptyState>
        )}
        {data.batches.map((b) => (
          <Bar
            key={String(b.batch_id)}
            frac={b.fill_rate}
            label={
              <span>
                {b.name ?? `batch ${b.batch_id}`} — {b.done}/{b.total} ({pct(b.fill_rate)})
              </span>
            }
          />
        ))}
      </Card>

      <Card
        headingLevel={3}
        title={
          <>
            Per-variant fill{" "}
            {data.variants.dimension ? (
              <Pill tone={data.variants.balanced ? "ok" : "warn"}>
                {data.variants.balanced ? "balanced" : "IMBALANCED"}
              </Pill>
            ) : (
              <Pill tone="muted">no variants</Pill>
            )}
          </>
        }
        description="Equal totals per value are the K/n counterbalancing invariant (§2.7)."
      >
        <PairedBar
          denom={variantDenom}
          rows={data.variants.values.map((v) => ({
            name: v.value ?? "all",
            filled: v.filled,
            total: v.total,
          }))}
        />
      </Card>

      <Card
        headingLevel={3}
        title="Per-key consensus"
        description={`Share of the ${data.consensus.complete_units} complete unit(s) that reached consensus.`}
      >
        {Object.keys(data.consensus.keys).length === 0 && (
          <EmptyState title="No complete units yet" data-testid="progress-consensus-empty">
            A unit is complete once it has all K labels. Consensus rates appear per answer key as
            units complete.
          </EmptyState>
        )}
        {Object.entries(data.consensus.keys).map(([key, k]) => (
          <Bar
            key={key}
            frac={k.rate ?? 0}
            color="var(--ok)"
            label={
              <span>
                <span className="mlp-mono">{key}</span> — {k.agreed}/{k.complete} ({pct(k.rate)})
              </span>
            }
          />
        ))}
      </Card>
    </div>
  );
}
