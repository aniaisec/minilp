"""Versioning diff (§2.5, §12 invariant 3).

Presentation-only edits (layout, render options, hotkeys, labels, description,
display blocks) update a template in place. Schema-affecting edits (inputs
added/removed/retyped, options changed, likert scale changed, variants changed)
bump the version so already-collected labels are never silently re-shaped.
"""

from typing import Any


def _input_signature(inp: dict[str, Any]) -> tuple:
    """The value-affecting projection of a single input."""
    return (
        inp["id"],
        inp["type"],
        tuple(inp.get("options", []) or []),
        bool(inp.get("allow_other", False)),
        bool(inp.get("required", False)),
        _scale_signature(inp.get("scale")),
    )


def _scale_signature(scale: dict[str, Any] | None) -> tuple:
    if not scale:
        return ()
    return (
        scale.get("min"),
        scale.get("max"),
        tuple(scale.get("labels", []) or []),
    )


def _schema_projection(schema: dict[str, Any]) -> dict[str, Any]:
    inputs = schema.get("inputs", []) or []
    return {
        # order matters: reordering inputs changes auto-hotkeys but not stored
        # value shape; however adding/removing/retyping must be detected, so we
        # compare the ordered list of signatures.
        "inputs": [_input_signature(i) for i in inputs],
        "variants": _normalize_variants(schema.get("variants")),
    }


def _normalize_variants(variants: dict[str, Any] | None) -> tuple:
    if not variants:
        return ()
    return (
        variants.get("dimension"),
        tuple(variants.get("values", []) or []),
    )


def is_schema_affecting(old_schema: dict[str, Any], new_schema: dict[str, Any]) -> bool:
    """True if the edit changes stored-value semantics and must bump the version."""
    return _schema_projection(old_schema) != _schema_projection(new_schema)
