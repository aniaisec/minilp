// Unit browser (§11): compose filters over units, open a per-unit detail drawer
// showing each label with annotator kind + reputation + variant, consensus and
// escalation state.

import { useCallback, useEffect, useState } from "react";

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

      {error && <div className="mlp-card mlp-error">{error}</div>}

      <table className="mlp-table mlp-card">
        <thead>
          <tr>
            <th>id</th>
            <th>status</th>
            <th>priority</th>
            <th>gold</th>
            <th>payload</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {units.map((u) => (
            <tr key={u.id}>
              <td className="mlp-mono">#{u.id}</td>
              <td>{u.status}</td>
              <td>{u.priority}</td>
              <td>{u.is_gold ? <Pill tone="warn">gold</Pill> : ""}</td>
              <td className="mlp-payload-cell">{JSON.stringify(u.payload)}</td>
              <td>
                <button className="mlp-btn" onClick={() => setSelected(u.id)}>
                  detail
                </button>
              </td>
            </tr>
          ))}
          {units.length === 0 && (
            <tr>
              <td colSpan={6} className="mlp-muted">
                No units match these filters.
              </td>
            </tr>
          )}
        </tbody>
      </table>

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
          <button className="mlp-btn" onClick={onClose}>
            close
          </button>
        </div>
        {error && <div className="mlp-error">{error}</div>}
        {!detail && !error && <p>Loading…</p>}
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
            <table className="mlp-table">
              <thead>
                <tr>
                  <th>annotator</th>
                  <th>kind</th>
                  <th>rep</th>
                  <th>variant</th>
                  <th>value</th>
                  <th>valid</th>
                </tr>
              </thead>
              <tbody>
                {detail.labels.map((l) => (
                  <tr key={l.label_id} className={l.is_valid ? "" : "mlp-voided"}>
                    <td className="mlp-mono">
                      {l.annotator_name ?? `#${l.annotator_id}`}
                    </td>
                    <td>{l.annotator_kind}</td>
                    <td>{l.reputation?.toFixed(2) ?? "—"}</td>
                    <td className="mlp-mono">{l.variant ? JSON.stringify(l.variant) : "—"}</td>
                    <td>{JSON.stringify(l.value)}</td>
                    <td>{l.is_valid ? "✓" : "voided"}</td>
                  </tr>
                ))}
              </tbody>
            </table>

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
