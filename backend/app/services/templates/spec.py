"""Template spec constants and the structural JSON Schema (§2.1-§2.4).

The JSON Schema covers *structure* (allowed types, enums, required keys); semantic
rules that JSON Schema can't express (id uniqueness, source resolution, hotkey
conflicts, variant divisibility) live in ``validation.py``.
"""

from typing import Any

# Display block types (§2.1)
DISPLAY_TYPES = ("text", "markdown", "image", "audio", "code", "html_snippet", "panel_group")

# Input field types (§2.1) and their canonical value shapes (§2.3)
INPUT_TYPES = ("radio", "checkbox", "likert", "free_text", "choice_buttons", "span_select")

# Which input types present selectable options that receive hotkeys (§2.4)
CHOICE_INPUT_TYPES = ("radio", "checkbox", "likert", "choice_buttons")
# Which input types carry an explicit ``options`` list
OPTION_INPUT_TYPES = ("radio", "checkbox", "choice_buttons")
# Which input types may set ``allow_other``
ALLOW_OTHER_TYPES = ("radio", "checkbox")

VALUE_SHAPES = {
    "radio": "string",
    "checkbox": "string[]",
    "likert": "int",
    "free_text": "string",
    "choice_buttons": "string",
    "span_select": "span[]",
}

# Layout (§2.2)
ARRANGEMENTS = ("stack", "split", "columns")
WIDTHS = ("md", "lg", "xl", "full")

# Per-block render options, validated per type (§2.2)
RENDER_OPTIONS: dict[str, set[str]] = {
    "text": {"collapsible", "max_lines"},
    "markdown": {"collapsible", "max_lines"},
    "image": {"fit", "zoom", "lightbox"},
    "audio": {"waveform", "playback_speed"},
    "code": {"language", "line_numbers"},
    "html_snippet": set(),
    "panel_group": {"sync_scroll", "diff_highlight"},
}

# Reserved keys (§2.4) — cannot be assigned to options.
RESERVED_ACTION_KEYS = frozenset({"s", "g", "d", "u", "?", "enter", "escape"})
# 'o' is reserved by auto-assignment for the allow_other "Other..." option.
OTHER_KEY = "o"
# Arrow key tokens usable by choice_buttons (§2.4)
ARROW_KEYS = frozenset({"left", "right", "up", "down"})
DIGIT_KEYS = tuple(str(d) for d in range(1, 10))
# Letters used for secondary choice inputs, minus reserved letters.
LETTER_KEYS = tuple(c for c in "abcefhijklmnpqrtvwxyz")  # excludes d,g,s,u,o

UNIT_REF_PREFIX = "$unit."


def value_shape(input_type: str) -> str:
    return VALUE_SHAPES[input_type]


# Structural JSON Schema (Draft 2020-12) for a template document.
TEMPLATE_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["name", "inputs"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "version": {"type": "integer", "minimum": 1},
        "description": {"type": ["string", "null"]},
        "layout": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "arrangement": {"enum": list(ARRANGEMENTS)},
                "ratio": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "minItems": 2,
                },
                "width": {"enum": list(WIDTHS)},
                "density": {"enum": ["comfortable", "compact"]},
            },
        },
        "display": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type"],
                "additionalProperties": False,
                "properties": {
                    "type": {"enum": list(DISPLAY_TYPES)},
                    "source": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                    "optional": {"type": "boolean"},
                    "render": {"type": "object"},
                },
            },
        },
        "inputs": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "type"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-zA-Z_][a-zA-Z0-9_]*$"},
                    "type": {"enum": list(INPUT_TYPES)},
                    "label": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "allow_other": {"type": "boolean"},
                    "required": {"type": "boolean"},
                    "hotkeys": {
                        "oneOf": [
                            {"const": "auto"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "scale": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "min": {"type": "integer"},
                            "max": {"type": "integer"},
                            "labels": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
        },
        "variants": {
            "type": ["object", "null"],
            "required": ["dimension", "values"],
            "additionalProperties": False,
            "properties": {
                "dimension": {"type": "string", "minLength": 1},
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                },
                "balance": {"enum": ["strict", "soft"]},
            },
        },
    },
}
