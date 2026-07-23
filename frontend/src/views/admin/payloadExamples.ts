// Build the example upload text a template expects, from its sample payload and
// field breakdown (§11 wizard). Pure so the exact shape shown to the user — and
// the required-field ordering — is unit-tested rather than eyeballed.

import type { PayloadFormat, TemplateSample } from "../../api/types";

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** A JSON-array example: one unit object with the sample payload + priority. */
export function jsonExample(sample: TemplateSample): string {
  return JSON.stringify([{ payload: sample.sample, priority: 0 }], null, 2);
}

/** A TSV example: header of payload fields (required first) + priority, one row. */
export function tsvExample(sample: TemplateSample): string {
  const fields = [...sample.fields.required, ...sample.fields.optional];
  const header = [...fields, "priority"];
  const row = [...fields.map((f) => cell(sample.sample[f])), "0"];
  return `${header.join("\t")}\n${row.join("\t")}`;
}

export function exampleFor(sample: TemplateSample, format: PayloadFormat): string {
  return format === "tsv" ? tsvExample(sample) : jsonExample(sample);
}

/** Client-side pre-check: which required fields the pasted/loaded content is
 *  missing, so the wizard can warn before the round-trip (the backend re-checks
 *  authoritatively per row). Returns [] when it can't tell (e.g. unparraseable). */
export function missingRequiredFields(
  content: string,
  format: PayloadFormat,
  required: string[],
): string[] {
  const trimmed = content.trim();
  if (!trimmed) return [];
  if (format === "tsv") {
    const header = trimmed.split(/\r?\n/)[0]?.split("\t").map((h) => h.trim()) ?? [];
    return required.filter((f) => !header.includes(f));
  }
  // JSON array: check the first object's payload keys.
  try {
    const data = JSON.parse(trimmed);
    const first = Array.isArray(data) ? data[0] : data;
    const payload = (first && (first.payload ?? first)) || {};
    return required.filter((f) => !(f in payload));
  } catch {
    return [];
  }
}
