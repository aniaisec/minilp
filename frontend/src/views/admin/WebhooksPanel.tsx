// Webhooks + delivery log (M7, §7.3).
//
// This sits under the Judges tab rather than in its own corner of the admin
// surface because that is what it is *for*: §7.3's argument is that budget and
// drift alerts are what make an unattended judge run safe to leave running. The
// alert config belongs next to the thing it guards.
//
// The delivery log is the half people forget to build. A webhook that has been
// quietly 404ing for a week looks exactly like a webhook that never needed to
// fire — until the invoice arrives. So failures are listed, in red, with the
// attempt count.

import { useCallback, useEffect, useState } from "react";

import type { MiniLpClient } from "../../api/client";
import type { Webhook, WebhookDelivery } from "../../api/types";

const EVENTS: { id: string; label: string; when: string; milestone?: string }[] = [
  {
    id: "budget.cap_reached",
    label: "Budget cap reached",
    when: "a judge run hard-stops on a $/token/label cap (§7.1)",
  },
  {
    id: "gold.accuracy_dropped",
    label: "Gold accuracy dropped",
    when: "an annotator or judge falls below the rolling gold threshold and is paused (§6.1)",
  },
  {
    id: "review.queue_backlog",
    label: "Review queue backlog",
    when: "escalated units pile up past the threshold (§7.2)",
    milestone: "M8",
  },
  {
    id: "project.completed",
    label: "Project completed",
    when: "every unit is finalized",
    milestone: "M8",
  },
];

export function WebhooksPanel({
  client,
  projectId,
}: {
  client: MiniLpClient;
  projectId: number;
}) {
  const [hooks, setHooks] = useState<Webhook[]>([]);
  const [deliveries, setDeliveries] = useState<WebhookDelivery[]>([]);
  const [event, setEvent] = useState(EVENTS[0].id);
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [scoped, setScoped] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [all, log] = await Promise.all([
        client.listWebhooks(),
        client.listDeliveries().catch(() => [] as WebhookDelivery[]),
      ]);
      // Instance-wide hooks fire for this project too, so both are relevant here.
      setHooks(all.filter((h) => h.project_id === null || h.project_id === projectId));
      setDeliveries(log.filter((d) => d.project_id === null || d.project_id === projectId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [client, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const create = () =>
    act(async () => {
      await client.createWebhook({
        event,
        target_url: url.trim(),
        secret: secret.trim() || null,
        project_id: scoped ? projectId : null,
      });
      setUrl("");
      setSecret("");
    });

  const active = EVENTS.find((e) => e.id === event);

  return (
    <div className="mlp-stack-lg" data-testid="webhooks-panel">
      <section className="mlp-card">
        <h3 style={{ marginTop: 0 }}>Alerts (§7.3)</h3>
        <p className="mlp-muted">
          Webhooks add no new trigger logic — they fire off checks that already run on every
          submit and every judge call. Deliveries are HMAC-signed with your secret and retried
          with backoff; the log below records every attempt.
        </p>

        {error && (
          <div className="mlp-error-text" data-testid="webhooks-error">
            {error}
          </div>
        )}

        {hooks.length === 0 ? (
          <p className="mlp-muted" data-testid="webhooks-empty">
            No webhooks registered for this project.
          </p>
        ) : (
          <table className="mlp-table" data-testid="webhooks-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Target</th>
                <th>Scope</th>
                <th>Signed</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {hooks.map((h) => (
                <tr key={h.id} data-testid={`webhook-row-${h.id}`}>
                  <td className="mlp-mono">{h.event}</td>
                  <td className="mlp-mono" style={{ wordBreak: "break-all" }}>
                    {h.target_url}
                  </td>
                  <td>{h.project_id === null ? "instance-wide" : "this project"}</td>
                  <td>{h.has_secret ? "yes" : "no"}</td>
                  <td>
                    <button
                      className="mlp-btn"
                      data-testid={`delete-webhook-${h.id}`}
                      disabled={busy}
                      onClick={() => void act(() => client.deleteWebhook(h.id))}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="mlp-stack" style={{ marginTop: 14 }}>
          <label className="mlp-block-label">
            Event
            <select
              value={event}
              data-testid="webhook-event"
              onChange={(e) => setEvent(e.target.value)}
            >
              {EVENTS.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.label}
                  {e.milestone ? ` (${e.milestone})` : ""}
                </option>
              ))}
            </select>
          </label>
          <p className="mlp-muted">Fires when {active?.when}.</p>
          <label className="mlp-block-label">
            Target URL
            <input
              value={url}
              data-testid="webhook-url"
              placeholder="https://hooks.example.com/minilp"
              onChange={(e) => setUrl(e.target.value)}
            />
          </label>
          <label className="mlp-block-label">
            Signing secret (optional)
            <input
              value={secret}
              data-testid="webhook-secret"
              placeholder="sent as X-MiniLP-Signature: sha256=…"
              onChange={(e) => setSecret(e.target.value)}
            />
          </label>
          <label className="mlp-inline-label">
            <input
              type="checkbox"
              checked={scoped}
              data-testid="webhook-scoped"
              onChange={(e) => setScoped(e.target.checked)}
            />
            Only this project (uncheck for instance-wide)
          </label>
          <div className="mlp-actions">
            <button
              className="mlp-btn mlp-btn-primary"
              data-testid="webhook-create"
              disabled={busy || !url.trim()}
              onClick={() => void create()}
            >
              Register webhook
            </button>
          </div>
        </div>
      </section>

      {deliveries.length > 0 && (
        <section className="mlp-card" data-testid="deliveries-panel">
          <h3 style={{ marginTop: 0 }}>Delivery log</h3>
          <table className="mlp-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Status</th>
                <th>Attempts</th>
                <th>Code</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.slice(0, 20).map((d) => (
                <tr key={d.id} data-testid={`delivery-${d.id}`}>
                  <td className="mlp-mono">{d.event}</td>
                  <td className={`mlp-status-${d.status}`}>{d.status}</td>
                  <td>{d.attempts}</td>
                  <td>{d.status_code ?? "—"}</td>
                  <td className="mlp-muted">{new Date(d.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {deliveries.some((d) => d.status === "failed") && (
            <p className="mlp-muted" style={{ marginTop: 8 }} data-testid="deliveries-warning">
              A failed delivery means the alert never reached anyone — the run still stopped
              at its cap, but nobody was told.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
