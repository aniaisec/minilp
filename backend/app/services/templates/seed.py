"""Gallery seed data — the built-in example templates (§3).

Each is a full working example an admin can clone and edit; the gallery is also the
template engine's test corpus (M1 acceptance: every gallery template round-trips
validate -> preview).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Template
from app.services.templates.validation import validate_template

# --- flagship: side-by-side preference (§3) ---
SIDE_BY_SIDE: dict[str, Any] = {
    "name": "side-by-side-preference",
    "version": 1,
    "description": "Prompt with two blinded response panels; pick the better one.",
    "layout": {"arrangement": "split", "ratio": [1, 1], "width": "xl"},
    "display": [
        {"type": "markdown", "source": "$unit.prompt", "render": {"collapsible": True}},
        {
            "type": "panel_group",
            "sources": ["$unit.response_a", "$unit.response_b"],
            "render": {"sync_scroll": True, "diff_highlight": True},
        },
    ],
    "inputs": [
        {
            "id": "choice",
            "type": "choice_buttons",
            "label": "Which response is better?",
            "options": ["Left", "Tie", "Right"],
            "hotkeys": ["←", "↓", "→"],
            "required": True,
        }
    ],
    "variants": {"dimension": "panel_order", "values": ["AB", "BA"], "balance": "strict"},
}

# --- image classification (§3) ---
IMAGE_CLASSIFICATION: dict[str, Any] = {
    "name": "image-classification",
    "version": 1,
    "description": "Classify an image into preset labels, with an Other escape hatch.",
    "layout": {"arrangement": "split", "ratio": [3, 2], "width": "xl"},
    "display": [
        {"type": "image", "source": "$unit.image_url", "render": {"fit": "contain", "zoom": True}},
        {
            "type": "text",
            "source": "$unit.context",
            "optional": True,
            "render": {"collapsible": True, "max_lines": 12},
        },
    ],
    "inputs": [
        {
            "id": "category",
            "type": "radio",
            "label": "What is shown in the image?",
            "options": ["cat", "dog", "bird"],
            "allow_other": True,
            "required": True,
            "hotkeys": "auto",
        }
    ],
    "variants": None,
}

# --- text sentiment (§3) ---
TEXT_SENTIMENT: dict[str, Any] = {
    "name": "text-sentiment",
    "version": 1,
    "description": "Sentiment of a passage plus a confidence rating.",
    "layout": {"arrangement": "stack", "width": "lg"},
    "display": [
        {"type": "text", "source": "$unit.text", "render": {"max_lines": 20}},
    ],
    "inputs": [
        {
            "id": "sentiment",
            "type": "radio",
            "label": "Overall sentiment",
            "options": ["positive", "neutral", "negative"],
            "required": True,
        },
        {
            "id": "confidence",
            "type": "likert",
            "label": "How confident are you?",
            "scale": {"min": 1, "max": 5},
            "required": False,
        },
    ],
    "variants": None,
}

# --- summary quality rating (§3) ---
SUMMARY_QUALITY: dict[str, Any] = {
    "name": "summary-quality",
    "version": 1,
    "description": "Rate a model summary against its source on three axes.",
    "layout": {"arrangement": "columns", "ratio": [1, 1], "width": "full"},
    "display": [
        {"type": "markdown", "source": "$unit.document", "render": {"collapsible": True}},
        {"type": "markdown", "source": "$unit.summary"},
    ],
    "inputs": [
        {
            "id": "faithfulness",
            "type": "likert",
            "label": "Faithfulness",
            "scale": {"min": 1, "max": 5},
            "required": True,
        },
        {
            "id": "coverage",
            "type": "likert",
            "label": "Coverage",
            "scale": {"min": 1, "max": 5},
            "required": True,
        },
        {
            "id": "fluency",
            "type": "likert",
            "label": "Fluency",
            "scale": {"min": 1, "max": 5},
            "required": True,
        },
        {"id": "comment", "type": "free_text", "label": "Comments", "required": False},
    ],
    "variants": None,
}

# --- toxicity / policy review (§3) ---
TOXICITY_REVIEW: dict[str, Any] = {
    "name": "toxicity-policy-review",
    "version": 1,
    "description": "Flag policy violations in a text or HTML snippet, with severity.",
    "layout": {"arrangement": "stack", "width": "lg"},
    "display": [
        {"type": "html_snippet", "source": "$unit.content"},
    ],
    "inputs": [
        {
            "id": "violations",
            "type": "checkbox",
            "label": "Violation categories",
            "options": ["hate", "harassment", "sexual", "violence", "self-harm"],
            "allow_other": True,
            "required": False,
        },
        {
            "id": "severity",
            "type": "radio",
            "label": "Severity",
            "options": ["none", "low", "medium", "high"],
            "required": True,
        },
    ],
    "variants": None,
}

# --- transcription check (§3) ---
TRANSCRIPTION_CHECK: dict[str, Any] = {
    "name": "transcription-check",
    "version": 1,
    "description": "Judge a candidate transcript against its audio and correct it.",
    "layout": {"arrangement": "stack", "width": "lg"},
    "display": [
        {"type": "audio", "source": "$unit.audio_url", "render": {"waveform": True}},
        {"type": "text", "source": "$unit.transcript"},
    ],
    "inputs": [
        {
            "id": "verdict",
            "type": "radio",
            "label": "Transcript accuracy",
            "options": ["correct", "minor errors", "wrong"],
            "required": True,
        },
        {"id": "correction", "type": "free_text", "label": "Correction", "required": False},
    ],
    "variants": None,
}

GALLERY: list[dict[str, Any]] = [
    SIDE_BY_SIDE,
    IMAGE_CLASSIFICATION,
    TEXT_SENTIMENT,
    SUMMARY_QUALITY,
    TOXICITY_REVIEW,
    TRANSCRIPTION_CHECK,
]


def validate_gallery() -> None:
    """Fail fast if any built-in template is malformed."""
    for schema in GALLERY:
        validate_template(schema)


def seed_templates(db: Session) -> list[Template]:
    """Insert the gallery as builtin templates (idempotent by name+version)."""
    validate_gallery()
    created: list[Template] = []
    for schema in GALLERY:
        exists = db.scalar(
            select(Template).where(
                Template.name == schema["name"],
                Template.version == schema.get("version", 1),
            )
        )
        if exists is not None:
            created.append(exists)
            continue
        tmpl = Template(
            name=schema["name"],
            version=schema.get("version", 1),
            description=schema.get("description"),
            kind="builtin",
            schema=schema,
        )
        db.add(tmpl)
        created.append(tmpl)
    db.flush()
    return created
