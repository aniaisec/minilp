// Token-layer tests (§ UX plan, phase 1).
//
// jsdom does not do layout or cascade, so there is no point asserting computed
// styles. What *can* be asserted — and is worth asserting, because these are
// the failures that shipped last time — are properties of the stylesheet
// itself: that no rule references a token that does not exist, that the
// disabled state does not go back to `opacity`, that the mode block still comes
// after the theme block, and that the accent ramps clear WCAG AA in every
// theme × mode combination.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "theme.css"), "utf8");

/** Declarations inside the first block with this exact selector list. */
function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector + " {");
  if (start < 0) throw new Error(`no block for ${selector}`);
  const body = css.slice(start + selector.length + 2, css.indexOf("}", start));
  const out: Record<string, string> = {};
  for (const line of body.split("\n")) {
    const m = /^\s*(--[\w-]+)\s*:\s*(.+?);\s*$/.exec(line);
    if (m) out[m[1]] = m[2].trim();
  }
  return out;
}

/** Later blocks win, then `var()` indirection is resolved to a literal. */
function resolve(...blocks: Record<string, string>[]): Record<string, string> {
  const merged = Object.assign({}, ...blocks) as Record<string, string>;
  const seen = new Set<string>();
  const deref = (value: string): string => {
    const m = /^var\((--[\w-]+)\)$/.exec(value.trim());
    if (!m) return value.trim();
    if (seen.has(m[1])) throw new Error(`circular token ${m[1]}`);
    seen.add(m[1]);
    const next = merged[m[1]];
    seen.delete(m[1]);
    return next ? deref(next) : value;
  };
  return Object.fromEntries(Object.entries(merged).map(([k, v]) => [k, deref(v)]));
}

function luminance(hex: string): number {
  const h = hex.trim().replace("#", "");
  const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
  const channel = (i: number) => {
    const v = parseInt(full.slice(i * 2, i * 2 + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const light = block(":root");
const dark = block('[data-theme="dark"]');
const teal = block('[data-mode="label"],\n[data-mode="review"]');
const tealDark = block('[data-theme="dark"][data-mode="label"],\n[data-theme="dark"][data-mode="review"]');

const COMBOS = {
  "admin · light": resolve(light),
  "admin · dark": resolve(light, dark),
  "label · light": resolve(light, teal),
  "label · dark": resolve(light, dark, tealDark),
};

describe("token layer", () => {
  it("defines every token it references", () => {
    const defined = new Set(Object.keys(resolve(light, dark, teal, tealDark)));
    const referenced = new Set(
      Array.from(css.matchAll(/var\((--[\w-]+)/g), (m) => m[1]),
    );
    // Two properties are supplied per-element by a widget rather than declared
    // in the token layer, and both have a fallback in the rule that reads them:
    // `--panel-count` (panel-group) and `--grid-ratio` (the template's own
    // split/columns ratio, passed as data so a media query can still fold the
    // grid — an inline `grid-template-columns` could not be overridden).
    referenced.delete("--panel-count");
    referenced.delete("--grid-ratio");

    expect([...referenced].filter((t) => !defined.has(t))).toEqual([]);
  });

  it("has no leftover --muted typos", () => {
    // Six rules referenced `--muted` where `--text-muted` was meant, so the
    // rating stars, palette headings and rank numbers inherited instead of
    // resolving. That is invisible until someone changes the inherited colour.
    expect(css).not.toMatch(/var\(--muted\)/);
  });

  it("expresses disabled state with tokens rather than opacity", () => {
    const disabledRule = /\.mlp-btn:disabled\s*{[^}]*}/.exec(css)?.[0] ?? "";
    expect(disabledRule).toContain("--disabled-");
    expect(disabledRule).not.toContain("opacity");
  });

  it("declares the mode block after the theme block", () => {
    // Same specificity, so source order is what decides the light/teal case.
    expect(css.indexOf('[data-mode="label"]')).toBeGreaterThan(
      css.indexOf('[data-theme="dark"] {'),
    );
    expect(css.indexOf('[data-theme="dark"][data-mode="label"]')).toBeGreaterThan(
      css.indexOf('[data-mode="label"],'),
    );
  });

  it("ships the primitives everything downstream depends on", () => {
    expect(css).toContain(":focus-visible");
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    expect(css).toContain(".mlp-visually-hidden");
  });

  it("uses a three-step radius and elevation scale", () => {
    for (const token of ["--radius-sm", "--radius", "--radius-lg"]) {
      expect(light[token]).toBeTruthy();
    }
    for (const token of ["--shadow-1", "--shadow-2", "--shadow-3"]) {
      expect(light[token]).toBeTruthy();
    }
    expect(light["--radius"]).toBe("8px");
    expect(light["--radius-lg"]).toBe("12px");
  });
});

describe("contrast (WCAG 2.2 AA)", () => {
  for (const [name, t] of Object.entries(COMBOS)) {
    describe(name, () => {
      it("body text clears 4.5:1 on both surfaces", () => {
        expect(contrast(t["--text"], t["--surface"])).toBeGreaterThanOrEqual(4.5);
        expect(contrast(t["--text"], t["--bg"])).toBeGreaterThanOrEqual(4.5);
      });

      it("muted text clears 4.5:1 on the surface it is used against", () => {
        // This is the one that was failing: #5b6472 on --surface-2 was 4.3:1.
        expect(contrast(t["--text-muted"], t["--surface-2"])).toBeGreaterThanOrEqual(4.5);
        expect(contrast(t["--text-muted"], t["--surface"])).toBeGreaterThanOrEqual(4.5);
      });

      it("the primary button clears 4.5:1", () => {
        expect(contrast(t["--accent-contrast"], t["--accent-strong"])).toBeGreaterThanOrEqual(
          4.5,
        );
      });

      it("accent text on its own soft tint clears 4.5:1", () => {
        // The active rail item: accent text on an accent-tinted background.
        expect(contrast(t["--accent-strong"], t["--accent-soft"])).toBeGreaterThanOrEqual(4.5);
      });

      it("the focus ring clears 3:1 against every surface it lands on", () => {
        for (const surface of ["--surface", "--surface-2", "--bg"]) {
          expect(contrast(t["--focus-ring"], t[surface])).toBeGreaterThanOrEqual(3);
        }
      });

      it("the mid accent clears 3:1 as a graphic", () => {
        expect(contrast(t["--accent"], t["--surface"])).toBeGreaterThanOrEqual(3);
      });

      it("disabled text clears 4.5:1 on its own background", () => {
        expect(contrast(t["--disabled-text"], t["--disabled-bg"])).toBeGreaterThanOrEqual(4.5);
      });
    });
  }
});
