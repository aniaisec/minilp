// Entry point for the visual-snapshot harness (scripts/snapshot.mjs).
//
// Bundled to a single self-contained HTML file so the admin surface can be
// opened — and screenshotted — from `file://` with no dev server, no backend,
// and no module loading (which `file://` blocks). It is not part of the app
// bundle: nothing in src/ imports this, and vite never sees it.
//
// The scenario is injected by the generated HTML as `window.__SNAP__`.

import { createRoot } from "react-dom/client";

import App from "../App";
import { ROUTES } from "./fixtures";

declare global {
  interface Window {
    __SNAP__?: { hash: string; theme?: "light" | "dark"; width?: number; collapsed?: boolean };
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
};
const realGetItem = Storage.prototype.getItem;
Storage.prototype.getItem = function (key: string) {
  return key in PREFS ? PREFS[key] : realGetItem.call(this, key);
};

window.location.hash = snap.hash;

createRoot(document.getElementById("root")!).render(<App />);

// Theme is component state inside the shell, not a prop, so the dark snapshot is
// taken by pressing the same control a person would. `data-testid` first, with a
// glyph fallback so this keeps working across the UX modernization (the toggle
// changes from an emoji button to an icon button in phase 2).
if (snap.theme === "dark") {
  setTimeout(() => {
    const byId = document.querySelector<HTMLButtonElement>('[data-testid="theme-toggle"]');
    const byGlyph = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("🌙"),
    );
    (byId ?? byGlyph)?.click();
  }, 50);
}

// Tells the screenshot driver the async fixture loads have settled.
setTimeout(() => document.documentElement.setAttribute("data-snapshot-ready", "1"), 400);
