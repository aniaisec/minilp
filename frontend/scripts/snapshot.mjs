// Build self-contained HTML snapshots of the admin surface for visual review.
//
//   node scripts/snapshot.mjs before      → docs/screenshots/before/*.html
//   node scripts/snapshot.mjs after       → docs/screenshots/after/*.html
//
// Each output is one file with the JS and CSS inlined, so it opens from
// `file://` in any browser with no server. That is what makes a before/after
// pair possible: the "before" files are generated from the pre-change tree and
// keep working after the source has moved on.
//
// Vite's library mode with an `iife` output, rather than the normal app build:
// the app build emits ES modules, and `file://` refuses to load those. No new
// dependency — this is the vite already in devDependencies.

import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { build as viteBuild } from "vite";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const label = process.argv[2] ?? "current";
const outDir = join(root, "..", "docs", "screenshots", label);

/** One file per scenario. `width` is advisory — the driver sets the viewport. */
const SCENARIOS = [
  { name: "dashboard-light", hash: "#/admin", theme: "light", width: 1440 },
  { name: "dashboard-dark", hash: "#/admin", theme: "dark", width: 1440 },
  { name: "project-light", hash: "#/admin/project/1", theme: "light", width: 1440 },
  { name: "project-dark", hash: "#/admin/project/1", theme: "dark", width: 1440 },
  // A section that is not the default, to show the secondary rail marking
  // something other than the first item — and, before phase 3, to show that
  // the URL could not name a section at all.
  { name: "project-units", hash: "#/admin/project/1/units", theme: "light", width: 1440 },
  { name: "project-narrow", hash: "#/admin/project/1", theme: "light", width: 1000 },
  { name: "dashboard-collapsed", hash: "#/admin", theme: "light", width: 1440, collapsed: true },
  { name: "dashboard-narrow", hash: "#/admin", theme: "light", width: 560 },
];

const result = await viteBuild({
  configFile: false,
  root,
  logLevel: "warn",
  plugins: [react()],
  define: { "process.env.NODE_ENV": '"production"' },
  build: {
    write: false,
    minify: true,
    target: "es2020",
    cssCodeSplit: false,
    lib: {
      entry: join(root, "src/snapshot/entry.tsx"),
      formats: ["iife"],
      name: "MlpSnapshot",
      fileName: () => "snapshot.js",
    },
  },
});

const outputs = (Array.isArray(result) ? result[0] : result).output;
const js = outputs.find((o) => o.fileName.endsWith(".js"))?.code ?? "";
const css = outputs.find((o) => o.fileName.endsWith(".css"))?.source ?? "";

rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });

for (const s of SCENARIOS) {
  const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>MiniLP snapshot — ${label} — ${s.name}</title>
    <style>${css}</style>
  </head>
  <body>
    <div id="root"></div>
    <script>window.__SNAP__ = ${JSON.stringify(s)};</script>
    <script>${js}</script>
  </body>
</html>
`;
  writeFileSync(join(outDir, `${s.name}.html`), html);
}

writeFileSync(
  join(outDir, "index.html"),
  `<!doctype html><meta charset="utf-8"><title>MiniLP snapshots — ${label}</title>
<style>body{font:15px system-ui;margin:40px;line-height:1.6}</style>
<h1>MiniLP admin snapshots — ${label}</h1>
<ul>${SCENARIOS.map((s) => `<li><a href="${s.name}.html">${s.name}</a> (${s.width}px)</li>`).join("")}</ul>
`,
);

// The side-by-side comparison sheet. Emitted here rather than kept as a file in
// the repo, because the whole docs/screenshots directory is gitignored — the
// generated bundles are several MB and regenerating them is one command. A
// hand-maintained sheet in a gitignored folder would simply get lost.
//
// Frames missing on disk render as empty boxes rather than breaking the page,
// so a sheet built from only one side is still readable.
const shotsDir = join(root, "..", "docs", "screenshots");
const PAIRS = [
  ["Dashboard — light", "dashboard-light", 1440],
  ["Dashboard — dark", "dashboard-dark", 1440],
  ["Project view — light", "project-light", 1440],
  ["Project view — dark", "project-dark", 1440],
  ["Project view — Units section (#/admin/project/1/units)", "project-units", 1440],
  ["Project view — 1000px, sections folded to a row", "project-narrow", 1000],
  ["Rail collapsed (mlp.navCollapsed = true)", "dashboard-collapsed", 1440],
  ["Narrow viewport — 560px", "dashboard-narrow", 560],
];

const section = ([heading, name, width]) => `
    <h2>${heading}</h2>
    <div class="pair" style="--shot-w: ${width}px">
      <figure>
        <figcaption>Before</figcaption>
        <div class="frame"><iframe src="before/${name}.html" title="Before — ${name}"></iframe></div>
      </figure>
      <figure>
        <figcaption>After</figcaption>
        <div class="frame"><iframe src="after/${name}.html" title="After — ${name}"></iframe></div>
      </figure>
    </div>`;

writeFileSync(
  join(shotsDir, "index.html"),
  `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>MiniLP admin surface — before / after</title>
    <style>
      :root { --shot-w: 1440px; --shot-h: 900px; --scale: 0.45; }
      body { margin: 0; padding: 28px 32px 60px; background: #eef0f3; color: #1a1d23;
             font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
      h1 { margin: 0 0 4px; font-size: 22px; }
      p.sub { margin: 0 0 24px; color: #4b5563; }
      h2 { margin: 28px 0 10px; font-size: 15px; text-transform: uppercase;
           letter-spacing: 0.06em; color: #4b5563; }
      .pair { display: grid; gap: 20px;
              grid-template-columns: repeat(2, calc(var(--shot-w) * var(--scale))); }
      figure { margin: 0; }
      figcaption { margin-bottom: 6px; font-size: 12px; font-weight: 650;
                   text-transform: uppercase; letter-spacing: 0.05em; color: #4b5563; }
      .frame { width: calc(var(--shot-w) * var(--scale));
               height: calc(var(--shot-h) * var(--scale)); overflow: hidden;
               border: 1px solid #c8cfd8; border-radius: 8px; background: #fff;
               box-shadow: 0 2px 8px rgba(16, 24, 40, 0.12); }
      .frame iframe { width: var(--shot-w); height: var(--shot-h); border: 0;
                      transform: scale(var(--scale)); transform-origin: 0 0; }
    </style>
  </head>
  <body>
    <h1>MiniLP admin surface — before / after</h1>
    <p class="sub">
      UX modernization plan, phases 1 (token layer), 2 (admin shell) and 3 (project view). Each frame is the real
      application rendered against fixture data, at a 1440×900 viewport unless noted.
      Regenerate with <code>node frontend/scripts/snapshot.mjs after</code>.
    </p>${PAIRS.map(section).join("")}
  </body>
</html>
`,
);

const kb = Math.round(readFileSync(join(outDir, `${SCENARIOS[0].name}.html`)).length / 1024);
console.log(`wrote ${SCENARIOS.length + 1} files to ${outDir} (${kb} KB each)`);
console.log(`comparison sheet: ${join(shotsDir, "index.html")}`);
