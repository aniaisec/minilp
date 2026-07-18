// Source resolution and variant-aware panel ordering (§2.1, §2.7, §3).

import type { DisplayBlock, TemplateSchema } from "../api/types";

const UNIT_REF_PREFIX = "$unit.";

export function refKey(source: string): string {
  return source.startsWith(UNIT_REF_PREFIX)
    ? source.slice(UNIT_REF_PREFIX.length)
    : source;
}

export function resolveSource(
  payload: Record<string, unknown>,
  source: string,
): unknown {
  return payload[refKey(source)];
}

// The variant value string for a template's variant dimension (e.g. "AB"), or null.
export function variantString(
  schema: TemplateSchema,
  variant: Record<string, unknown> | null | undefined,
): string | null {
  const dim = schema.variants?.dimension;
  if (!dim || !variant) return null;
  const v = variant[dim];
  return typeof v === "string" ? v : null;
}

// For a panel_group, return the display sources reordered per the active variant.
// Sources are given in canonical item order (A, B, …); a variant string like
// "BA" is a permutation of item letters mapping panel position → item.
export function orderedPanelSources(
  block: DisplayBlock,
  variant: string | null,
): { source: string; item: string }[] {
  const sources = block.sources ?? (block.source ? [block.source] : []);
  const items = sources.map((_, i) => String.fromCharCode(65 + i)); // A, B, C…
  if (!variant) {
    return sources.map((source, i) => ({ source, item: items[i] }));
  }
  const out: { source: string; item: string }[] = [];
  for (const ch of variant) {
    const idx = ch.charCodeAt(0) - 65; // 'A' -> 0
    if (idx >= 0 && idx < sources.length) {
      out.push({ source: sources[idx], item: ch });
    }
  }
  return out.length === sources.length
    ? out
    : sources.map((source, i) => ({ source, item: items[i] }));
}
