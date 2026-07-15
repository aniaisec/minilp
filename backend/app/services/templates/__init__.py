"""Template engine — the core product (§2 of PLAN.md).

Public surface:
- ``validate_template`` / ``TemplateValidationError`` — §2.1–§2.4 validation.
- ``assign_hotkeys`` — auto/explicit hotkey resolution + conflict detection (§2.4).
- ``is_schema_affecting`` — versioning diff (§2.5).
- ``render_preview`` — render-check a sample unit payload (§2.5, §5).
- ``required_sources`` — payload keys a unit must supply (ingest validation).
"""

from app.services.templates.hotkeys import assign_hotkeys
from app.services.templates.preview import render_preview, required_sources
from app.services.templates.validation import (
    TemplateValidationError,
    validate_template,
)
from app.services.templates.versioning import is_schema_affecting

__all__ = [
    "TemplateValidationError",
    "assign_hotkeys",
    "is_schema_affecting",
    "render_preview",
    "required_sources",
    "validate_template",
]
