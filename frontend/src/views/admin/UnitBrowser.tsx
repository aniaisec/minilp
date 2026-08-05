// Unit browser (§11): compose filters over units, open a per-unit detail drawer
// showing each label with annotator kind + reputation + variant, consensus and
// escalation state.

import { useCallback, useEffect, useState } from "react";

import { Button, Card, EmptyState, ErrorState, Table } from "../../components/ui";
import type { MiniLpClient } from "../../api/client";
import type { Batch, UnitDetail, UnitSummary } from "../../api/types";
import { Pill } from "./widgets";

const STATUSES = ["", "pending", "in_progress", "labeled", "finalized"];

export function UnitBrowser({ client, projectId }: { client: MiniLpClient; projectId: number }) {
  const [units, setUnits] = useState<UnitSummary[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [status, setStatus] = useState("");
  const [batchId, setBatchId] = useState("");
  const [gold, setGold] = useState("");
  const [escalated, setEscalated] = useState(false);
  const [minPriority, setMinPriority] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    client.listBatches(projectId).then(setBatches).catch(() => setBatches([]));
  }, [client, projectId]);

  const load = useCallback(() => {
    const q: Record<string, string | number | boolean> = {};
    if (status) q.status = status;
    if (batchId) q.batch_id = Number(batchId);
    if (gold) q.is_gold = gold === "gold";
    if (escalated) q.escalated = true;
    if (minPriority) q.min_priority = Number(minPriority);
    client
      .listUnits(projectId, q)
      .then(setUnits)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [client, projectId, status, batchId, gold, escalated, minPriority]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="mlp-unit-browser">
      <div className="mlp-filters mlp-card">
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s || "any"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Batch
          <select value={batchId} onChange={(e) => setBatchId(e.target.value)}>
            <option value="">any</option>
            {batches.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name ?? `batch ${b.id}`}
              </option>
            ))}
          </select>
        </label>
        <label>
          Gold
          <select value={gold} onChange={(e) => setGold(e.target.value)}>
            <option value="">any</option>
            <option value="gold">gold only</option>
            <option value="normal">non-gold</option>
          </select>
        </label>
        <label>
          Min priority
          <input
            type="number"
            value={minPriority}
            onChange={(e) => setMinPriority(e.target.value)}
            style={{ width: 70 }}
          />
        </label>
        <label className="mlp-check">
          <input
            type="checkbox"
            checked={escalated}
            onChange={(e) => setEscalated(e.target.checked)}
          />
          escalated
        </label>
      </div>

      {error && (
        <Card>
          <ErrorState title="Could not load units" data-testid="units-error">
            {error}
          </ErrorState>
        </Card>
      )}

      <Table
        className="mlp-card"
        caption="Units in this project matching the current filters"
        columns={[
          "id",
          "status",
          "priority",
          "gold",
          "payload",
          { srLabel: "Actions" },
        ]}
        isEmpty={units.length === 0}
        empty={
          <EmptyState title="No units match these filters" data-testid="units-empty">
            Widen the filters above, or add tasks to this project from the Add tasks section.
          </EmptyState>
        }
      >
        {units.map((u) => (
          <tr key={u.id}>
            <td className="mlp-mono">#{u.id}</td>
            <td>{u.status}</td>
            <td>{u.priority}</td>
            <td>{u.is_gold ? <Pill tone="warn">gold</Pill> : ""}</td>
            <td className="mlp-payload-cell">{JSON.stringify(u.payload)}</td>
            <td>
              {/* Ghost: one of these sits in every row, and a bordered button
                  per row turns the table into a column of buttons with some
                  data beside them. */}
              <Button variant="ghost" size="sm" onClick={() => setSelected(u.id)}>
                detail
              </Button>
            </td>
          </tr>
        ))}
      </Table>

      {selected !== null && (
        <UnitDrawer client={client} unitId={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function UnitDrawer({
  client,
  unitId,
  onClose,
}: {
  client: MiniLpClient;
  unitId: number;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<UnitDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    client
      .getUnit(unitId)
      .then(setDetail)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [client, unitId]);

  return (
    <div className="mlp-drawer-scrim" onClick={onClose}>
      <aside className="mlp-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="mlp-drawer-head">
          <h3>Unit #{unitId}</h3>
          <Button onClick={onClose}>close</Button>
        </div>
        {error && (
          <ErrorState title="Could not load this unit" inline data-testid="unit-detail-error">
            {error}
          </ErrorState>
        )}
        {!detail && !error && (
          <p className="mlp-muted" role="status">
            Loading unit…
          </p>
        )}
        {detail && (
          <>
            <div className="mlp-kv">
              <span>Status</span>
              <span>{detail.status}</span>
              <span>Priority</span>
              <span>{detail.priority}</span>
              <span>Gold</span>
              <span>{detail.is_gold ? "yes" : "no"}</span>
              <span>Escalated</span>
              <span>{detail.escalated_at ? detail.escalated_at : "no"}</span>
            </div>

            <h4>Payload</h4>
            <pre className="mlp-pre">{JSON.stringify(detail.payload, null, 2)}</pre>

            <h4>Labels ({detail.labels.length})</h4>
            <Table
              caption={`Labels submitted on unit ${unitId}`}
              columns={["annotator", "kind", "rep", "variant", "value", "valid"]}
              isEmpty={detail.labels.length === 0}
              empty={
                <EmptyState title="No labels on this unit yet" data-testid="unit-labels-empty">
                  This unit is still waiting for its first submission.
                </EmptyState>
              }
            >
              {detail.labels.map((l) => (
                <tr key={l.label_id} className={l.is_valid ? "" : "mlp-voided"}>
                  <td className="mlp-mono">{l.annotator_name ?? `#${l.annotator_id}`}</td>
                  <td>{l.annotator_kind}</td>
                  <td>{l.reputation?.toFixed(2) ?? "—"}</td>
                  <td className="mlp-mono">{l.variant ? JSON.stringify(l.variant) : "—"}</td>
                  <td>{JSON.stringify(l.value)}</td>
                  <td>{l.is_valid ? "✓" : "voided"}</td>
                </tr>
              ))}
            </Table>

            {detail.consensus && (
              <>
                <h4>Consensus</h4>
                <pre className="mlp-pre">{JSON.stringify(detail.consensus, null, 2)}</pre>
              </>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
