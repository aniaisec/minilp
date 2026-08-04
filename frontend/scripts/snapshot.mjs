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

const kb = Math.round(readFileSync(join(outDir, `${SCENARIOS[0].name}.html`)).length / 1024);
console.log(`wrote ${SCENARIOS.length + 1} files to ${outDir} (${kb} KB each)`);
