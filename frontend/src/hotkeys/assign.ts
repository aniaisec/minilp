// Hotkey auto-assignment, explicit overrides, and conflict detection (§2.4).
// A faithful port of backend `services/templates/hotkeys.py` so the badges the
// annotator sees exactly match what validation accepted at template save time.

import type { InputField } from "../api/types";

// Reserved action keys (§2.4) — cannot be assigned to options.
export const RESERVED_ACTION_KEYS = new Set([
  "s",
  "g",
  "d",
  "u",
  "?",
  "enter",
  "escape",
]);
export const OTHER_KEY = "o";
export const ARROW_KEYS = new Set(["left", "right", "up", "down"]);
export const DIGIT_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"];
// Letters for secondary choice inputs, minus reserved letters (d,g,s,u,o).
export const LETTER_KEYS = "abcefhijklmnpqrtvwxyz".split("");

const ARROW_ALIASES: Record<string, string> = {
  "←": "left",
  "→": "right",
  "↑": "up",
  "↓": "down",
  arrowleft: "left",
  arrowright: "right",
  arrowup: "up",
  arrowdown: "down",
};

export function normalizeKey(key: string): string {
  const k = key.trim().toLowerCase();
  return ARROW_ALIASES[k] ?? k;
}

const CHOICE_INPUT_TYPES = new Set(["radio", "checkbox", "likert", "choice_buttons"]);

export interface InputHotkeys {
  // option label -> normalized key
  options: Record<string, string>;
  // key for the allow_other "Other…" entry, if any
  other: string | null;
}

export interface HotkeyAssignment {
  byInput: Record<string, InputHotkeys>;
  errors: string[];
}

export function optionLabels(inp: InputField): string[] {
  if (inp.type === "likert") {
    const scale = inp.scale ?? {};
    if (scale.labels) return [...scale.labels];
    const lo = scale.min ?? 1;
    const hi = scale.max ?? 5;
    const out: string[] = [];
    for (let n = lo; n <= hi; n++) out.push(String(n));
    return out;
  }
  return [...(inp.options ?? [])];
}

export function assignHotkeys(inputs: InputField[]): HotkeyAssignment {
  const byInput: Record<string, InputHotkeys> = {};
  const errors: string[] = [];
  const used: Record<string, string> = {}; // key -> "where" for duplicate reporting
  let choiceSeen = 0;
  let letterCursor = 0;

  const claim = (rawKey: string, where: string): void => {
    const key = normalizeKey(rawKey);
    if (RESERVED_ACTION_KEYS.has(key)) {
      errors.push(
        `hotkey '${key}' for ${where} collides with a reserved key ` +
          `(${[...RESERVED_ACTION_KEYS].sort().join(", ")})`,
      );
      return;
    }
    if (key in used) {
      errors.push(`duplicate hotkey '${key}': used by both ${used[key]} and ${where}`);
      return;
    }
    used[key] = where;
  };

  for (const inp of inputs) {
    const entry: InputHotkeys = { options: {}, other: null };
    byInput[inp.id] = entry;

    const labels = optionLabels(inp);
    const isChoice = CHOICE_INPUT_TYPES.has(inp.type);
    const hk = inp.hotkeys ?? "auto";

    if (Array.isArray(hk)) {
      if (isChoice && hk.length !== labels.length) {
        errors.push(
          `input '${inp.id}': explicit hotkeys length ${hk.length} != option count ${labels.length}`,
        );
      }
      labels.forEach((label, i) => {
        if (i < hk.length) {
          entry.options[label] = normalizeKey(hk[i]);
          claim(hk[i], `input '${inp.id}' option '${label}'`);
        }
      });
    } else if (isChoice) {
      if (choiceSeen === 0) {
        labels.forEach((label, i) => {
          if (i < DIGIT_KEYS.length) {
            const key = DIGIT_KEYS[i];
            entry.options[label] = key;
            claim(key, `input '${inp.id}' option '${label}'`);
          } else {
            errors.push(`input '${inp.id}': more options than available digit keys`);
          }
        });
      } else {
        for (const label of labels) {
          if (letterCursor < LETTER_KEYS.length) {
            const key = LETTER_KEYS[letterCursor++];
            entry.options[label] = key;
            claim(key, `input '${inp.id}' option '${label}'`);
          } else {
            errors.push(`input '${inp.id}': ran out of auto letter keys`);
          }
        }
      }
      choiceSeen += 1;
    }

    if (inp.allow_other) {
      entry.other = OTHER_KEY;
      claim(OTHER_KEY, `input '${inp.id}' Other`);
    }
  }

  return { byInput, errors };
}

// Pretty label for a key badge: arrows render as glyphs, others uppercase-ish.
const ARROW_GLYPH: Record<string, string> = {
  left: "←",
  right: "→",
  up: "↑",
  down: "↓",
};
export function keyBadgeLabel(key: string): string {
  const k = normalizeKey(key);
  return ARROW_GLYPH[k] ?? k.toUpperCase();
}
