import type { DisplayBlock } from "../../api/types";

// Common props for every display widget (§2.6 extensibility contract).
export interface DisplayWidgetProps {
  block: DisplayBlock;
  payload: Record<string, unknown>;
  // Variant string (e.g. "AB") driving panel ordering; null for variant-free.
  variant: string | null;
}

export function asString(v: unknown): string {
  if (v == null) return "";
  return typeof v === "string" ? v : String(v);
}

export type { DisplayBlock };
