"""Hotkey auto-assignment, explicit overrides, and conflict detection (§2.4).

``assign_hotkeys`` is pure: it takes the ``inputs`` list from a template schema and
returns a per-input key map plus a list of conflict errors. Validation surfaces the
errors; the renderer/preview uses the map to draw badges.
"""

from typing import Any

from app.services.templates.spec import (
    ARROW_KEYS,
    CHOICE_INPUT_TYPES,
    DIGIT_KEYS,
    LETTER_KEYS,
    OTHER_KEY,
    RESERVED_ACTION_KEYS,
)

# Human-friendly aliases accepted in explicit hotkey lists for arrow keys.
_ARROW_ALIASES = {
    "←": "left",
    "→": "right",
    "↑": "up",
    "↓": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "arrowup": "up",
    "arrowdown": "down",
}


def normalize_key(key: str) -> str:
    """Lowercase and map arrow glyphs/aliases to canonical tokens."""
    k = key.strip().lower()
    return _ARROW_ALIASES.get(k, k)


class HotkeyAssignment:
    """Result of assigning hotkeys to a template's inputs."""

    def __init__(self) -> None:
        # input_id -> {"options": {option_label: key}, "other": key|None}
        self.by_input: dict[str, dict[str, Any]] = {}
        self.errors: list[str] = []

    def key_map(self, input_id: str) -> dict[str, str]:
        entry = self.by_input.get(input_id, {})
        m = dict(entry.get("options", {}))
        if entry.get("other"):
            m["__other__"] = entry["other"]
        return m


def _option_labels(inp: dict[str, Any]) -> list[str]:
    if inp["type"] == "likert":
        scale = inp.get("scale") or {}
        if "labels" in scale:
            return list(scale["labels"])
        lo = scale.get("min", 1)
        hi = scale.get("max", 5)
        return [str(n) for n in range(lo, hi + 1)]
    return list(inp.get("options", []) or [])


def assign_hotkeys(inputs: list[dict[str, Any]]) -> HotkeyAssignment:
    """Assign hotkeys across all inputs and detect conflicts (§2.4)."""
    result = HotkeyAssignment()
    used: dict[str, str] = {}  # key -> "input_id/option" for duplicate reporting
    choice_seen = 0
    letter_cursor = 0  # global cursor into LETTER_KEYS across secondary inputs

    def claim(key: str, where: str) -> None:
        key = normalize_key(key)
        if key in RESERVED_ACTION_KEYS:
            result.errors.append(
                f"hotkey '{key}' for {where} collides with a reserved key "
                f"({', '.join(sorted(RESERVED_ACTION_KEYS))})"
            )
            return
        if key in used:
            result.errors.append(f"duplicate hotkey '{key}': used by both {used[key]} and {where}")
            return
        used[key] = where

    for inp in inputs:
        iid = inp["id"]
        itype = inp["type"]
        entry: dict[str, Any] = {"options": {}, "other": None}
        result.by_input[iid] = entry

        labels = _option_labels(inp)
        is_choice = itype in CHOICE_INPUT_TYPES
        hk = inp.get("hotkeys", "auto")

        if isinstance(hk, list):
            # Explicit override: one key per option, in order (§2.4).
            if is_choice and len(hk) != len(labels):
                result.errors.append(
                    f"input '{iid}': explicit hotkeys length {len(hk)} "
                    f"!= option count {len(labels)}"
                )
            for label, key in zip(labels, hk, strict=False):
                entry["options"][label] = normalize_key(key)
                claim(key, f"input '{iid}' option '{label}'")
        elif is_choice:
            # Auto assignment (§2.4): the first choice input's options get digits
            # 1..9; subsequent inputs draw letters from a single shared pool so
            # keys never collide across inputs.
            if choice_seen == 0:
                for i, label in enumerate(labels):
                    if i < len(DIGIT_KEYS):
                        key = DIGIT_KEYS[i]
                        entry["options"][label] = key
                        claim(key, f"input '{iid}' option '{label}'")
                    else:
                        result.errors.append(
                            f"input '{iid}': more options than available digit keys"
                        )
            else:
                for label in labels:
                    if letter_cursor < len(LETTER_KEYS):
                        key = LETTER_KEYS[letter_cursor]
                        letter_cursor += 1
                        entry["options"][label] = key
                        claim(key, f"input '{iid}' option '{label}'")
                    else:
                        result.errors.append(f"input '{iid}': ran out of auto letter keys")
            choice_seen += 1

        # allow_other gets 'o' (§2.4)
        if inp.get("allow_other"):
            entry["other"] = OTHER_KEY
            claim(OTHER_KEY, f"input '{iid}' Other")

    return result


def is_valid_key_token(key: str) -> bool:
    k = normalize_key(key)
    return len(k) == 1 or k in ARROW_KEYS or k in RESERVED_ACTION_KEYS
