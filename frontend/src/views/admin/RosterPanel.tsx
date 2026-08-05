// Annotator roster (§11 dashboard): who labeled this project, with live
// reputation, gold accuracy, volume and pause state.

import { useEffect, useState } from "react";

import { Card, EmptyState, ErrorState, Table } from "../../components/ui";
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

  if (error)
    return (
      <Card>
        <ErrorState title="Could not load the roster" data-testid="roster-error">
          {error}
        </ErrorState>
      </Card>
    );
  if (!roster)
    return (
      <Card>
        <p className="mlp-muted" role="status">
          Loading roster…
        </p>
      </Card>
    );

  return (
    <Card
      headingLevel={3}
      title={`Annotators (${roster.count})`}
      description="Everyone who has submitted a label on this project, human or judge."
    >
      <Table
        caption="Annotators on this project, with reputation and volume"
        columns={[
          "annotator",
          "kind",
          "status",
          "reputation",
          "gold",
          "labels",
          "voided",
        ]}
        isEmpty={roster.count === 0}
        empty={
          <EmptyState title="No annotators yet" data-testid="roster-empty">
            Nobody has submitted a label on this project. Once someone starts labeling they appear
            here with their reputation and gold accuracy.
          </EmptyState>
        }
      >
        {roster.annotators.map((a) => (
          <tr key={a.annotator_id}>
            <td className="mlp-mono">{a.display_name ?? `#${a.annotator_id}`}</td>
            <td>{a.kind}</td>
            <td>{a.status === "active" ? a.status : <Pill tone="warn">{a.status}</Pill>}</td>
            <td>{a.reputation.toFixed(3)}</td>
            <td>
              {a.gold_total ? `${pct(a.gold_accuracy)} (${a.gold_passes}/${a.gold_total})` : "—"}
            </td>
            <td>{a.labels_valid}</td>
            <td>{a.labels_voided || ""}</td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}
