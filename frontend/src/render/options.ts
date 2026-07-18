// Resolved options + selection reducers shared by input widgets and the central
// keyboard dispatcher, so mouse and keyboard produce identical raw answers.

import type { InputField } from "../api/types";
import { optionLabels, type InputHotkeys } from "../hotkeys/assign";
import { OTHER_PREFIX } from "./canonical";

export interface ResolvedOption {
  label: string;
  key?: string; // hotkey token
  raw: string | number; // raw value contributed when chosen
}

// Options in order, each with its hotkey and the raw value it contributes.
// likert options resolve to integers (min + index); others to their label.
export function resolveOptions(input: InputField, hotkeys: InputHotkeys): ResolvedOption[] {
  const labels = optionLabels(input);
  if (input.type === "likert") {
    const min = input.scale?.min ?? 1;
    return labels.map((label, i) => ({
      label,
      key: hotkeys.options[label],
      raw: min + i,
    }));
  }
  return labels.map((label) => ({
    label,
    key: hotkeys.options[label],
    raw: label,
  }));
}

export function isOtherActive(input: InputField, current: unknown): boolean {
  if (!input.allow_other) return false;
  if (input.type === "checkbox") {
    return Array.isArray(current) && current.some((v) => isOtherRaw(v));
  }
  return isOtherRaw(current);
}

export function isOtherRaw(v: unknown): boolean {
  return typeof v === "string" && v.startsWith(OTHER_PREFIX);
}

export function otherText(current: unknown): string {
  if (Array.isArray(current)) {
    const found = current.find((v) => isOtherRaw(v));
    return typeof found === "string" ? found.slice(OTHER_PREFIX.length) : "";
  }
  return isOtherRaw(current) ? (current as string).slice(OTHER_PREFIX.length) : "";
}

// Apply choosing a concrete option to the current raw value.
export function applyOption(
  input: InputField,
  current: unknown,
  opt: ResolvedOption,
): unknown {
  if (input.type === "checkbox") {
    const arr = Array.isArray(current) ? [...current] : [];
    const idx = arr.indexOf(opt.raw);
    if (idx >= 0) arr.splice(idx, 1);
    else arr.push(opt.raw);
    return arr;
  }
  return opt.raw;
}

// Apply / update the free-text "Other…" entry.
export function applyOther(input: InputField, current: unknown, text: string): unknown {
  const raw = OTHER_PREFIX + text;
  if (input.type === "checkbox") {
    const arr = (Array.isArray(current) ? current : []).filter((v) => !isOtherRaw(v));
    arr.push(raw);
    return arr;
  }
  return raw;
}

// Toggle whether the Other entry is active (used when the 'o' hotkey is pressed).
export function toggleOther(input: InputField, current: unknown): unknown {
  if (isOtherActive(input, current)) {
    if (input.type === "checkbox") {
      return (Array.isArray(current) ? current : []).filter((v) => !isOtherRaw(v));
    }
    return undefined;
  }
  return applyOther(input, current, "");
}
