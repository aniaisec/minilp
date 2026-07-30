// Route wrapper for the review queue (M8) — resolves nothing but the exit
// control, so `Review` itself stays a plain component the tests can mount with a
// mock client.

import { ExitToHome } from "../components/ExitToHome";
import type { MiniLpClient } from "../api/client";
import { Review } from "./Review";

export function ReviewPage({
  client,
  projectId,
  homeHref,
}: {
  client: MiniLpClient;
  apiKey?: string;
  projectId?: number;
  /** Absent when the reviewer opened the queue directly rather than from home. */
  homeHref?: string;
}) {
  return (
    <div className="mlp-app">
      <Review
        client={client}
        projectId={projectId}
        exit={
          homeHref ? (
            // No hotkey here: `x` is free in the annotation view but the review
            // queue already spends its single letters on approve/override/next,
            // and a reviewer mid-override should not lose the page to a stray key.
            <ExitToHome href={homeHref} hotkey={false} label="Home" />
          ) : null
        }
      />
    </div>
  );
}
