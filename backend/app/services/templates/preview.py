"""Render-check a sample unit payload against a template (§2.5, §5).

``required_sources`` — the payload keys a unit must supply (non-optional display
blocks); reused by bulk ingest to reject malformed rows.
``render_preview`` — assemble the resolved view a human/judge would see: display
blocks with values filled in, inputs with their assigned hotkeys and badges.
"""

from typing import Any

from app.services.templates.hotkeys import assign_hotkeys
from app.services.templates.spec import UNIT_REF_PREFIX, value_shape
from app.services.templates.validation import reserved_keys


def _ref_key(source: str) -> str:
    return source[len(UNIT_REF_PREFIX) :] if source.startswith(UNIT_REF_PREFIX) else source


def required_sources(schema: dict[str, Any]) -> list[str]:
    """Payload keys required by non-optional display blocks."""
    keys: list[str] = []
    for block in schema.get("display", []) or []:
        if block.get("optional"):
            continue
        srcs = []
        if "source" in block:
            srcs.append(block["source"])
        srcs.extend(block.get("sources", []) or [])
        for src in srcs:
            if src.startswith(UNIT_REF_PREFIX):
                key = _ref_key(src)
                if key not in keys:
                    keys.append(key)
    return keys


def validate_payload(schema: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """Return a list of problems for a unit payload against the template.

    An empty list means the payload is valid.
    """
    problems: list[str] = []
    if not isinstance(payload, dict):
        return ["payload must be a JSON object"]
    for key in required_sources(schema):
        if key not in payload or payload[key] in (None, ""):
            problems.append(f"missing required payload field '{key}'")
    return problems


def render_preview(schema: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Assemble a resolved preview of a unit under the template.

    Does not raise on missing payload fields — it marks them ``resolved: False`` so
    the editor can show a live preview even mid-edit. Callers wanting strict
    validation use ``validate_payload``.
    """
    assignment = assign_hotkeys(schema.get("inputs", []) or [])

    blocks = []
    for block in schema.get("display", []) or []:
        srcs = []
        if "source" in block:
            srcs.append(block["source"])
        srcs.extend(block.get("sources", []) or [])
        resolved_values = {}
        all_resolved = True
        for src in srcs:
            key = _ref_key(src)
            present = isinstance(payload, dict) and key in payload
            all_resolved = all_resolved and present
            resolved_values[src] = payload.get(key) if present else None
        blocks.append(
            {
                "type": block.get("type"),
                "sources": srcs,
                "values": resolved_values,
                "optional": bool(block.get("optional", False)),
                "render": block.get("render") or {},
                "resolved": all_resolved,
            }
        )

    inputs = []
    for inp in schema.get("inputs", []) or []:
        inputs.append(
            {
                "id": inp["id"],
                "type": inp["type"],
                "label": inp.get("label", ""),
                "options": inp.get("options", []),
                "required": bool(inp.get("required", False)),
                "value_shape": value_shape(inp["type"]),
                "hotkeys": assignment.key_map(inp["id"]),
            }
        )

    return {
        "layout": schema.get("layout") or {"arrangement": "stack"},
        "display": blocks,
        "inputs": inputs,
        "variants": schema.get("variants"),
        "reserved_keys": sorted(reserved_keys()),
        "payload_valid": validate_payload(schema, payload) == [],
    }
