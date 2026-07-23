// Progress view (§11): status funnel, per-batch bars, per-variant paired bars
// (counterbalancing proof), per-key consensus rates, throughput + ETA.

import { useEffect, useState } from "react";

import type { MiniLpClient } from "../../api/client";
import type { Progress } from "../../api/types";
import { eta, pct } from "./format";
import { Bar, PairedBar, Pill, StatCard } from "./widgets";

export function ProgressPanel({ client, projectId }: { client: MiniLpClient; projectId: number }) {
  const [data, setData] = useState<Progress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    client
      .getProgress(projectId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [client, projectId]);

  if (error) return <div className="mlp-card mlp-error">{error}</div>;
  if (!data) return <div className="mlp-card">Loading progress…</div>;

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

      <section className="mlp-card">
        <h3>Status funnel</h3>
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
      </section>

      <section className="mlp-card">
        <h3>Per-batch fill</h3>
        {data.batches.length === 0 && <p className="mlp-muted">No batches yet.</p>}
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
      </section>

      <section className="mlp-card">
        <h3>
          Per-variant fill{" "}
          {data.variants.dimension ? (
            <Pill tone={data.variants.balanced ? "ok" : "warn"}>
              {data.variants.balanced ? "balanced" : "IMBALANCED"}
            </Pill>
          ) : (
            <Pill tone="muted">no variants</Pill>
          )}
        </h3>
        <p className="mlp-muted">
          Equal totals per value are the K/n counterbalancing invariant (§2.7).
        </p>
        <PairedBar
          denom={variantDenom}
          rows={data.variants.values.map((v) => ({
            name: v.value ?? "all",
            filled: v.filled,
            total: v.total,
          }))}
        />
      </section>

      <section className="mlp-card">
        <h3>Per-key consensus</h3>
        <p className="mlp-muted">
          Share of the {data.consensus.complete_units} complete unit(s) that reached consensus.
        </p>
        {Object.keys(data.consensus.keys).length === 0 && (
          <p className="mlp-muted">No complete units yet.</p>
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
      </section>
    </div>
  );
}
