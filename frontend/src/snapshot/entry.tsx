// Entry point for the visual-snapshot harness (scripts/snapshot.mjs).
//
// Bundled to a single self-contained HTML file so a surface can be opened — and
// screenshotted — from `file://` with no dev server, no backend, and no module
// loading (which `file://` blocks). It is not part of the app bundle: nothing
// in src/ imports this, and vite never sees it.
//
// The scenario is injected by the generated HTML as `window.__SNAP__`.

import { createRoot } from "react-dom/client";

import App from "../App";
import { Annotate } from "../views/Annotate";
import type { TaskClient } from "../api/client";
import type { SubmitRequest, Task, TemplateSchema } from "../api/types";
import { LABEL_GUIDELINES, LABEL_SCHEMA, LABEL_TASK, ROUTES } from "./fixtures";

declare global {
  interface Window {
    __SNAP__?: {
      hash: string;
      /** Which surface to mount. Admin routes through `App`; the labeler view is
       *  mounted directly, since its config lives in the query string and a
       *  `file://` document cannot reliably carry one. */
      view?: "admin" | "annotate";
      theme?: "light" | "dark";
      width?: number;
      collapsed?: boolean;
      /** `data-testid`s clicked once the surface has loaded, in order — used to
       *  reach a state that is otherwise only reachable by interaction (a filled
       *  answer, an open dialog). */
      clicks?: string[];
    };
  }
}

const snap = window.__SNAP__ ?? { hash: "#/admin" };

// Stand in for the backend. Anything unmatched 404s rather than hanging, so a
// missing fixture shows up as a visible error state instead of a stuck spinner.
window.fetch = (input: RequestInfo | URL): Promise<Response> => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  for (const [pattern, body] of ROUTES) {
    if (pattern.test(url)) {
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
  }
  return Promise.resolve(
    new Response(JSON.stringify({ detail: `no fixture for ${url}` }), { status: 404 }),
  );
};

// The admin shell reads its key from the URL or from storage; seed storage so
// the snapshot shows the loaded surface rather than the "paste a key" prompt.
// Answer the app's preference reads directly rather than seeding storage.
//
// Seeding does not work here, and the reason is worth writing down. Chrome
// gives every `file://` document the same storage partition, so all the frames
// in the comparison sheet share one `localStorage`. Worse, React 18's `render`
// is asynchronous: each frame writes its value, then yields, and by the time
// any frame's `useState` initialiser actually runs, a later frame has already
// overwritten the key. Every scenario ended up rendering the last one's state.
//
// Intercepting the read is immune to both: nothing is shared, and the timing
// no longer matters.
const PREFS: Record<string, string> = {
  "mlp.apiKey": "snapshot-key",
  "mlp.navCollapsed": String(snap.collapsed ?? false),
  "mlp.autoSubmit": "0",
};
const realGetItem = Storage.prototype.getItem;
Storage.prototype.getItem = function (key: string) {
  return key in PREFS ? PREFS[key] : realGetItem.call(this, key);
};

// The labeler surface never runs out of work in a snapshot: the same unit comes
// back every time, so a stray submit cannot leave the frame on "all caught up".
const labelClient: TaskClient = {
  nextTask: () => Promise.resolve(LABEL_TASK as Task),
  submit: (slotId: number, annotatorId: number, body: SubmitRequest) =>
    Promise.resolve({
      id: 1,
      slot_id: slotId,
      unit_id: LABEL_TASK.unit_id,
      annotator_id: annotatorId,
      value: body.value ?? {},
      is_valid: true,
    }),
  skip: (slotId: number) => Promise.resolve({ slot_id: slotId, status: "open" }),
};

const root = createRoot(document.getElementById("root")!);

if (snap.view === "annotate") {
  root.render(
    <Annotate
      client={labelClient}
      annotatorId={42}
      projectId={1}
      projectName="Image QA · furniture catalogue"
      schema={LABEL_SCHEMA as unknown as TemplateSchema}
      guidelines={LABEL_GUIDELINES}
      sessionGoal={12}
      homeHref="annotator=42&key=snapshot-key"
    />,
  );
} else {
  window.location.hash = snap.hash;
  root.render(<App />);
}

// Theme is component state inside each shell, not a prop, so the dark snapshot
// is taken by pressing the same control a person would. `data-testid` first,
// with a glyph fallback so this keeps working across the UX modernization (the
// toggles change from emoji buttons to icon buttons over phases 2 and 4).
if (snap.theme === "dark") {
  setTimeout(() => {
    const byId = document.querySelector<HTMLButtonElement>(
      '[data-testid="theme-toggle"], [data-testid="btn-theme"]',
    );
    const byGlyph = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("🌙"),
    );
    (byId ?? byGlyph)?.click();
  }, 50);
}

// Interaction steps, spaced out so each one's render has landed before the next
// looks for its target. Missing targets are skipped rather than thrown: a
// scenario that names a control the *before* tree does not have should still
// produce a frame, because "this did not exist yet" is the comparison.
(snap.clicks ?? []).forEach((testid, i) => {
  setTimeout(
    () => document.querySelector<HTMLElement>(`[data-testid="${testid}"]`)?.click(),
    120 + i * 40,
  );
});

// Tells the screenshot driver the async fixture loads have settled.
setTimeout(() => document.documentElement.setAttribute("data-snapshot-ready", "1"), 600);
