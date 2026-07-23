// Bias analytics view (§9): variant-preference with CIs (humans vs judges),
// per-annotator bias, per-unit order sensitivity, and label distribution (§11).

import { useEffect, useState } from "react";

import type { MiniLpClient } from "../../api/client";
import type { Bias, BiasGroup, Distribution } from "../../api/types";
import { ci, pct, ranked, total } from "./format";
import { Bar, Pill, StatCard } from "./widgets";

function GroupCard({ title, g }: { title: string; g: BiasGroup }) {
  if (g.n_positional_labels === 0) {
    return (
      <div className="mlp-card">
        <h3>{title}</h3>
        <p className="mlp-muted">No positional labels yet.</p>
      </div>
    );
  }
  return (
    <div className="mlp-card">
      <h3>{title}</h3>
      <div className="mlp-stat-row">
        <StatCard label="Prefer first (CI)" value={ci(g.prefer_first_rate)} />
        <StatCard
          label="Bias score"
          value={g.bias_score?.toFixed(2) ?? "—"}
          sub={`${g.n_positional_labels} labels`}
        />
      </div>
      <table className="mlp-table">
        <thead>
          <tr>
            <th>Annotator</th>
            <th>first</th>
            <th>second</th>
            <th>prefer-first (CI)</th>
            <th>bias</th>
          </tr>
        </thead>
        <tbody>
          {g.annotators.map((a) => (
            <tr key={a.annotator_id}>
              <td className="mlp-mono">#{a.annotator_id}</td>
              <td>{a.first}</td>
              <td>{a.second}</td>
              <td>{ci(a.preference)}</td>
              <td>{a.bias_score?.toFixed(2) ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BiasPanel({ client, projectId }: { client: MiniLpClient; projectId: number }) {
  const [bias, setBias] = useState<Bias | null>(null);
  const [dist, setDist] = useState<Distribution | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setBias(null);
    setDist(null);
    setError(null);
    Promise.all([client.getBias(projectId), client.getDistribution(projectId)])
      .then(([b, d]) => {
        setBias(b);
        setDist(d);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [client, projectId]);

  if (error) return <div className="mlp-card mlp-error">{error}</div>;
  if (!bias || !dist) return <div className="mlp-card">Loading analytics…</div>;

  const os = bias.order_sensitivity;

  return (
    <div className="mlp-stack-lg">
      <GroupCard title="Humans — order bias" g={bias.humans} />
      <GroupCard title="Judges — order bias" g={bias.judges} />

      <section className="mlp-card">
        <h3>
          Order sensitivity{" "}
          {os.flip_rate !== null && (
            <Pill tone={os.flip_rate > 0 ? "warn" : "ok"}>{pct(os.flip_rate)} flip</Pill>
          )}
        </h3>
        <p className="mlp-muted">
          Units whose canonical winner changes across variant presentations — candidates for extra
          labels or review (§9).
        </p>
        <div className="mlp-stat-row">
          <StatCard label="Measurable units" value={os.measurable_units} />
          <StatCard label="Flipped units" value={os.flipped_units} />
        </div>
        {os.units.filter((u) => u.flipped).length > 0 && (
          <p className="mlp-muted">
            Flipped: {os.units.filter((u) => u.flipped).map((u) => `#${u.unit_id}`).join(", ")}
          </p>
        )}
      </section>

      <section className="mlp-card">
        <h3>Label distribution</h3>
        <p className="mlp-muted">Canonical answers per key across all valid labels (§11).</p>
        {Object.entries(dist.keys).map(([key, k]) => {
          const denom = total(k.overall) || 1;
          return (
            <div key={key} className="mlp-dist-key">
              <div className="mlp-mono mlp-dist-title">{key}</div>
              {ranked(k.overall).map(([val, count]) => (
                <Bar
                  key={val}
                  frac={count / denom}
                  label={
                    <span>
                      {val} — {count} ({pct(count / denom)})
                    </span>
                  }
                />
              ))}
            </div>
          );
        })}
      </section>
    </div>
  );
}
