// Resolved options + selection reducers shared by input widgets and the central
// keyboard dispatcher, so mouse and keyboard produce identical raw answers.

import type { InputField } from "../api/types";
import { optionLabels, type InputHotkeys } from "../hotkeys/assign";
import { OTHER_PREFIX } from "./canonical";

export interface ResolvedOption {
  label: string;
  key?: string; // hotkey token
  raw: string | number | boolean; // raw value contributed when chosen
}

// Input types whose answer is an array, so picking an option toggles membership.
const MULTI_TYPES = new Set(["checkbox", "multiselect"]);

// Options in order, each with its hotkey and the raw value it contributes.
// likert/rating options resolve to integers (min + index), boolean to true/false,
// everything else to its own label.
export function resolveOptions(input: InputField, hotkeys: InputHotkeys): ResolvedOption[] {
  const labels = optionLabels(input);
  if (input.type === "likert" || input.type === "rating") {
    const min = input.scale?.min ?? 1;
    return labels.map((label, i) => ({
      label,
      key: hotkeys.options[label],
      raw: min + i,
    }));
  }
  if (input.type === "boolean") {
    return labels.map((label, i) => ({
      label,
      key: hotkeys.options[label],
      raw: i === 0, // Yes → true, No → false
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
  if (MULTI_TYPES.has(input.type)) {
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
  if (MULTI_TYPES.has(input.type)) {
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
  if (MULTI_TYPES.has(input.type)) {
    const arr = (Array.isArray(current) ? current : []).filter((v) => !isOtherRaw(v));
    arr.push(raw);
    return arr;
  }
  return raw;
}

// Toggle whether the Other entry is active (used when the 'o' hotkey is pressed).
export function toggleOther(input: InputField, current: unknown): unknown {
  if (isOtherActive(input, current)) {
    if (MULTI_TYPES.has(input.type)) {
      return (Array.isArray(current) ? current : []).filter((v) => !isOtherRaw(v));
    }
    return undefined;
  }
  return applyOther(input, current, "");
}

/** The ordered list a `ranking` input starts from, or the current order. */
export function rankingOrder(input: InputField, current: unknown): string[] {
  const options = input.options ?? [];
  if (!Array.isArray(current)) return [...options];
  const chosen = current.filter((v): v is string => typeof v === "string" && options.includes(v));
  // Anything the answer is missing (a newly added option) goes on the end.
  return [...chosen, ...options.filter((o) => !chosen.includes(o))];
}

/** Move an item within a ranking by `delta` positions; returns the new order. */
export function moveInOrder(order: string[], index: number, delta: number): string[] {
  const target = index + delta;
  if (target < 0 || target >= order.length) return order;
  const next = [...order];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
