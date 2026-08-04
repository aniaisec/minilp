// "Start labeling" — the admin's way into the annotation view (§11).
//
// The gap this closes: an admin holds a *user* token and the annotation view
// wants an *annotator* id. Those are different things by design (§4 — a user is
// an access principal, an annotator is a rater), and until now the only way to
// bridge them was to go and look one up in the database. So the button resolves
// it on click via `POST /me:annotator`, which creates the rater record on first
// use and returns the same one every time after.
//
// It navigates rather than rendering the annotation view in place. The two
// surfaces are separate top-level modes (App switches on the hash), and more to
// the point: the annotation view is a keyboard-first, full-attention screen, and
// embedding it inside admin chrome would mean the `?` overlay, `g`, `d` and the
// digit keys all compete with whatever else is on the page.

import { useState, type ReactNode } from "react";

import type { MiniLpClient } from "../../api/client";

/** The annotation-view URL for a project, or the task landing page without one. */
export function labelingUrl(annotatorId: number, apiKey: string, projectId?: number): string {
  const params = new URLSearchParams();
  if (projectId !== undefined) params.set("project", String(projectId));
  params.set("annotator", String(annotatorId));
  if (apiKey) params.set("key", apiKey);
  // Explicitly drop the hash: App routes on `#/admin`, so leaving it would land
  // the annotator back in the admin surface.
  return `${window.location.pathname}?${params.toString()}`;
}

export function StartLabeling({
  client,
  projectId,
  apiKey,
  label = "Start labeling →",
  className = "mlp-btn mlp-btn-primary",
  navigate = (url: string) => {
    window.location.href = url;
  },
}: {
  client: MiniLpClient;
  /** Omit to open the annotator's task landing page instead of one project. */
  projectId?: number;
  apiKey: string;
  /** A node, not just a string: the rail renders it as icon + label + tooltip. */
  label?: ReactNode;
  className?: string;
  /** Injectable so tests can assert the URL without a jsdom navigation. */
  navigate?: (url: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      const me = await client.myAnnotator();
      navigate(labelingUrl(me.id, apiKey, projectId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        className={className}
        data-testid="start-labeling"
        disabled={busy}
        title="Open the annotation view as yourself — your labels count like anyone else's"
        onClick={(e) => {
          e.stopPropagation(); // the project card is itself clickable
          void go();
        }}
      >
        {busy ? "Opening…" : label}
      </button>
      {error && (
        <span className="mlp-error-text" data-testid="start-labeling-error">
          {error}
        </span>
      )}
    </>
  );
}
