// Annotator roster (§11 dashboard): who labeled this project, with live
// reputation, gold accuracy, volume and pause state.

import { useEffect, useState } from "react";

import type { MiniLpClient } from "../../api/client";
import type { Roster } from "../../api/types";
import { pct } from "./format";
import { Pill } from "./widgets";

export function RosterPanel({ client, projectId }: { client: MiniLpClient; projectId: number }) {
  const [roster, setRoster] = useState<Roster | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRoster(null);
    setError(null);
    client
      .getRoster(projectId)
      .then(setRoster)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [client, projectId]);

  if (error) return <div className="mlp-card mlp-error">{error}</div>;
  if (!roster) return <div className="mlp-card">Loading roster…</div>;
  if (roster.count === 0) return <div className="mlp-card mlp-muted">No annotators yet.</div>;

  return (
    <div className="mlp-card">
      <h3>Annotators ({roster.count})</h3>
      <table className="mlp-table">
        <thead>
          <tr>
            <th>annotator</th>
            <th>kind</th>
            <th>status</th>
            <th>reputation</th>
            <th>gold</th>
            <th>labels</th>
            <th>voided</th>
          </tr>
        </thead>
        <tbody>
          {roster.annotators.map((a) => (
            <tr key={a.annotator_id}>
              <td className="mlp-mono">{a.display_name ?? `#${a.annotator_id}`}</td>
              <td>{a.kind}</td>
              <td>
                {a.status === "active" ? (
                  a.status
                ) : (
                  <Pill tone="warn" >{a.status}</Pill>
                )}
              </td>
              <td>{a.reputation.toFixed(3)}</td>
              <td>
                {a.gold_total ? `${pct(a.gold_accuracy)} (${a.gold_passes}/${a.gold_total})` : "—"}
              </td>
              <td>{a.labels_valid}</td>
              <td>{a.labels_voided || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
