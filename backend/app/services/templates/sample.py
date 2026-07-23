"""Example unit payloads for a template — the gallery preview + wizard prefill (M5).

``payload_fields`` reports which payload keys a template reads and whether each is
required (non-optional display block) or optional. ``sample_payload`` builds a
plausible example object for those keys, typed by the display block that consumes
them (an image field gets a URL, a text field gets a sentence), so the gallery can
show a working preview and the wizard can show the exact shape an upload needs.

``get_sample`` returns the template's saved sample when present, otherwise a freshly
generated one; ``save_sample`` validates a proposed sample carries every required
field before persisting it (editing a sample never bumps the schema version — it is
presentation metadata, §2.5).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Template
from app.services.templates.preview import required_sources, validate_payload
from app.services.templates.spec import UNIT_REF_PREFIX


def _ref_key(source: str) -> str:
    return source[len(UNIT_REF_PREFIX) :] if source.startswith(UNIT_REF_PREFIX) else source


def _field_types(schema: dict[str, Any]) -> dict[str, str]:
    """Map each referenced payload key to the display block type that reads it."""
    out: dict[str, str] = {}
    for block in schema.get("display", []) or []:
        btype = block.get("type", "text")
        srcs = []
        if "source" in block:
            srcs.append(block["source"])
        srcs.extend(block.get("sources", []) or [])
        for src in srcs:
            if src.startswith(UNIT_REF_PREFIX):
                out.setdefault(_ref_key(src), btype)
    return out


def payload_fields(schema: dict[str, Any]) -> dict[str, list[str]]:
    """{'required': [...], 'optional': [...]} payload keys for the template."""
    required = required_sources(schema)
    types = _field_types(schema)
    optional = [k for k in types if k not in required]
    return {"required": required, "optional": optional}


_EXAMPLES: dict[str, Any] = {
    "image": "https://example.com/sample-image.png",
    "audio": "https://example.com/sample-audio.mp3",
    "code": 'def greet(name):\n    return f"hello {name}"',
    "html_snippet": "<p>Example HTML snippet.</p>",
    "markdown": "**Example** prompt text the annotator will read.",
    "panel_group": "An example response to compare.",
    "text": "Example text for this field.",
}


def _example_for(key: str, block_type: str) -> Any:
    return _EXAMPLES.get(block_type, f"example {key}")


def sample_payload(schema: dict[str, Any]) -> dict[str, Any]:
    """A plausible example payload covering every referenced field (required first)."""
    types = _field_types(schema)
    fields = payload_fields(schema)
    ordered = fields["required"] + fields["optional"]
    return {key: _example_for(key, types.get(key, "text")) for key in ordered}


class SampleError(ValueError):
    """A proposed sample is missing required fields."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def get_sample(db: Session, template: Template) -> dict[str, Any]:
    """The saved sample, or a generated one, plus the field breakdown."""
    saved = template.sample is not None
    payload = template.sample if saved else sample_payload(template.schema)
    return {
        "template_id": template.id,
        "saved": saved,
        "sample": payload,
        "fields": payload_fields(template.schema),
    }


def save_sample(db: Session, template: Template, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a sample after checking it satisfies the template's required fields."""
    problems = validate_payload(template.schema, payload)
    if problems:
        raise SampleError(problems)
    template.sample = payload
    db.add(template)
    db.flush()
    return get_sample(db, template)
