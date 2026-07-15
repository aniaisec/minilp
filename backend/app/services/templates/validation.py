"""Template validation (§2.1-§2.4).

Two layers:
1. Structural — the JSON Schema in ``spec.py`` (types, enums, required keys).
2. Semantic — rules JSON Schema can't express: unique input ids, option/render
   constraints per type, ``$unit`` source refs, hotkey conflicts, variant spec.

``validate_template`` raises ``TemplateValidationError`` carrying *all* errors so a
template author sees every problem at once, not one at a time.
"""

from typing import Any

from jsonschema import Draft202012Validator

from app.services.templates.hotkeys import assign_hotkeys
from app.services.templates.spec import (
    ALLOW_OTHER_TYPES,
    ARROW_KEYS,
    OPTION_INPUT_TYPES,
    RENDER_OPTIONS,
    RESERVED_ACTION_KEYS,
    TEMPLATE_JSON_SCHEMA,
    UNIT_REF_PREFIX,
)

_structural = Draft202012Validator(TEMPLATE_JSON_SCHEMA)


class TemplateValidationError(ValueError):
    """Raised when a template fails validation; ``errors`` lists every problem."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _structural_errors(schema: dict[str, Any]) -> list[str]:
    errors = []
    for err in sorted(_structural.iter_errors(schema), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "<root>"
        errors.append(f"{loc}: {err.message}")
    return errors


def _semantic_errors(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    # --- inputs: ids unique, per-type constraints ---
    seen_ids: set[str] = set()
    for inp in schema.get("inputs", []) or []:
        iid = inp.get("id")
        itype = inp.get("type")
        if iid in seen_ids:
            errors.append(f"duplicate input id '{iid}'")
        seen_ids.add(iid)

        has_options = bool(inp.get("options"))
        if itype in OPTION_INPUT_TYPES:
            opts = inp.get("options") or []
            if len(opts) < 2:
                errors.append(f"input '{iid}' ({itype}) needs at least 2 options")
            if len(set(opts)) != len(opts):
                errors.append(f"input '{iid}' has duplicate options")
        elif has_options:
            errors.append(f"input '{iid}' ({itype}) must not declare options")

        if inp.get("allow_other") and itype not in ALLOW_OTHER_TYPES:
            errors.append(f"input '{iid}' ({itype}) does not support allow_other")

        if itype == "likert":
            scale = inp.get("scale") or {}
            if "labels" not in scale:
                lo, hi = scale.get("min", 1), scale.get("max", 5)
                if hi <= lo:
                    errors.append(f"input '{iid}' likert scale max must exceed min")

        # explicit arrow keys only valid for choice_buttons
        hk = inp.get("hotkeys", "auto")
        if isinstance(hk, list) and itype != "choice_buttons":
            from app.services.templates.hotkeys import normalize_key

            for key in hk:
                if normalize_key(key) in ARROW_KEYS:
                    errors.append(
                        f"input '{iid}' ({itype}): arrow keys are only for choice_buttons"
                    )

    # --- display: source refs well-formed ---
    for i, block in enumerate(schema.get("display", []) or []):
        btype = block.get("type")
        srcs = []
        if "source" in block:
            srcs.append(block["source"])
        srcs.extend(block.get("sources", []) or [])
        if btype != "panel_group" and not srcs:
            errors.append(f"display[{i}] ({btype}) requires a source")
        for src in srcs:
            if not src.startswith(UNIT_REF_PREFIX):
                errors.append(f"display[{i}] source '{src}' must be a $unit.<key> reference")
        # render options validated per type
        render = block.get("render") or {}
        allowed = RENDER_OPTIONS.get(btype, set())
        for key in render:
            if key not in allowed:
                errors.append(
                    f"display[{i}] ({btype}) render option '{key}' is not valid "
                    f"(allowed: {sorted(allowed) or 'none'})"
                )

    # --- layout: ratio arity matches split ---
    layout = schema.get("layout") or {}
    if layout.get("arrangement") == "split" and "ratio" in layout and len(layout["ratio"]) != 2:
        errors.append("layout.ratio must have exactly 2 entries for a split arrangement")

    # --- variants ---
    variants = schema.get("variants")
    if variants:
        values = variants.get("values", [])
        if len(set(values)) != len(values):
            errors.append("variants.values must be unique")

    # --- hotkeys: conflicts (duplicate / reserved) ---
    inputs = schema.get("inputs", []) or []
    if inputs and not any(e for e in errors if "options" in e or "at least 2" in e):
        assignment = assign_hotkeys(inputs)
        errors.extend(assignment.errors)

    return errors


def validate_template(schema: dict[str, Any]) -> None:
    """Validate a template document. Raises ``TemplateValidationError`` on failure."""
    if not isinstance(schema, dict):
        raise TemplateValidationError(["template must be a JSON object"])

    errors = _structural_errors(schema)
    if errors:
        # Skip semantic checks if the shape is wrong — they assume valid structure.
        raise TemplateValidationError(errors)

    errors = _semantic_errors(schema)
    if errors:
        raise TemplateValidationError(errors)


# Convenience for callers wanting the reserved key set (e.g. UI overlay).
def reserved_keys() -> set[str]:
    return set(RESERVED_ACTION_KEYS)
