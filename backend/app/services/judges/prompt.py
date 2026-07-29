"""Prompt assembly (§7.1) — project guidelines + template serialization + unit
payload + strict answer-format instructions.

The design rule here is the one that makes the whole platform's headline metric
possible: **a judge sees what a human sees**. The panels are ordered by the slot's
variant, positions are named the way the widget names them ("Left" / "Right"), and
nothing in the text says which item is A and which is B. A judge that always picks
the left panel then produces exactly the same measurable order bias a human does,
through the same `raw` → `value` canonicalization (§2.8, §9). Serializing the items
as "Response A / Response B" would quietly destroy that — the judge would answer in
canonical space and every position-bias number would read 0.5 by construction.

The other rule is the blinding surface (DESIGN.md postmortem 2): model names,
variant values and gold status never enter the prompt. A gold unit is serialized
identically to any other unit, because a judge told "this one is scored" is not
measuring the same thing.

The serialization is deliberately plain text rather than JSON: it renders once,
reads like a task, and stays stable under template edits that only change
presentation — which is what keeps the response cache (§4) hitting.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.services.quality.canonical import positional_variant
from app.services.templates.spec import BOOLEAN_LABELS, UNIT_REF_PREFIX, value_shape

DEFAULT_SYSTEM = (
    "You are a careful annotator working through a labeling task. "
    "Follow the guidelines exactly, judge only what you are shown, and answer "
    "in the required JSON format with no extra commentary."
)

# Human-readable position names, used in the order the panels are presented.
POSITION_NAMES = ("Left", "Right", "Third", "Fourth")


@dataclass(frozen=True)
class JudgePrompt:
    system: str
    user: str
    #  The input ids the judge is expected to answer, in template order.
    field_ids: list[str]

    def digest(self) -> str:
        """Stable hash over what was actually sent — the cache's guard (§4)."""
        return hashlib.sha256(f"{self.system}\x00{self.user}".encode()).hexdigest()


def _ref_key(source: str) -> str:
    return source[len(UNIT_REF_PREFIX) :] if source.startswith(UNIT_REF_PREFIX) else source


def _ordered_panel_sources(block: dict[str, Any], variant: str | None) -> list[str]:
    """Panel sources in presentation order (mirrors ``orderedPanelSources``).

    A variant string like ``"BA"`` is a permutation of item letters mapping panel
    *position* → item, so the judge reads the panels in the same physical order a
    human with that slot would.
    """
    sources = list(block.get("sources") or ([block["source"]] if block.get("source") else []))
    if not variant:
        return sources
    out: list[str] = []
    for char in variant:
        idx = ord(char.upper()) - ord("A")
        if 0 <= idx < len(sources):
            out.append(sources[idx])
    return out if len(out) == len(sources) else sources


def _render_value(value: Any) -> str:
    if value is None:
        return "(not provided)"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def serialize_display(
    schema: dict[str, Any], payload: dict[str, Any], variant: str | None
) -> list[str]:
    """Render the display blocks as labeled text sections, in variant order."""
    sections: list[str] = []
    for block in schema.get("display") or []:
        btype = block.get("type", "text")
        if btype == "panel_group":
            for position, source in enumerate(_ordered_panel_sources(block, variant)):
                name = (
                    POSITION_NAMES[position]
                    if position < len(POSITION_NAMES)
                    else f"Panel {position + 1}"
                )
                value = payload.get(_ref_key(source))
                if value is None and block.get("optional"):
                    continue
                sections.append(f"### {name}\n{_render_value(value)}")
            continue

        sources = list(block.get("sources") or ([block["source"]] if block.get("source") else []))
        for source in sources:
            key = _ref_key(source)
            value = payload.get(key)
            if value is None and block.get("optional"):
                continue
            heading = key.replace("_", " ").strip().capitalize() or btype
            if btype in ("image", "audio"):
                sections.append(f"### {heading} ({btype} at {_render_value(value)})")
            elif btype == "code":
                language = (block.get("render") or {}).get("language", "")
                sections.append(f"### {heading}\n```{language}\n{_render_value(value)}\n```")
            else:
                sections.append(f"### {heading}\n{_render_value(value)}")
    return sections


def _field_options(field: dict[str, Any]) -> list[str] | None:
    ftype = field.get("type")
    if ftype == "boolean":
        return list(BOOLEAN_LABELS)
    options = field.get("options")
    if options:
        return [str(o) for o in options]
    scale = field.get("scale")
    if ftype in ("likert", "rating") and isinstance(scale, dict):
        low = int(scale.get("min", 1))
        high = int(scale.get("max", 5))
        labels = scale.get("labels") or []
        if labels and len(labels) == (high - low + 1):
            return [f"{low + i} ({label})" for i, label in enumerate(labels)]
        return [str(n) for n in range(low, high + 1)]
    return None


def serialize_inputs(schema: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Render the answer schema. Returns (lines, field_ids).

    The line format — ``- "id" (type): label`` — is also what the mock provider
    parses to produce a shaped answer, so the fake judge exercises the same
    serialization the real ones read rather than a convenient parallel format.
    """
    lines: list[str] = []
    ids: list[str] = []
    for field in schema.get("inputs") or []:
        fid = field.get("id")
        if not fid:
            continue
        ids.append(fid)
        ftype = field.get("type", "free_text")
        label = field.get("label") or fid
        required = "required" if field.get("required") else "optional"
        line = f'- "{fid}" ({ftype}): {label} [{required}, value shape: {value_shape(ftype)}]'
        options = _field_options(field)
        if options:
            line += f"\n    one of: {json.dumps(options, ensure_ascii=False)}"
            if ftype in ("checkbox", "multiselect", "tags", "ranking"):
                line += "  (answer with an array)"
        if field.get("allow_other"):
            line += '\n    if none fit, answer "other:<your label>"'
        low, high = field.get("min"), field.get("max")
        if low is not None or high is not None:
            line += f"\n    range: {low if low is not None else '-inf'}..{high}"
        if field.get("help"):
            line += f"\n    note: {field['help']}"
        lines.append(line)
    return lines, ids


ANSWER_INSTRUCTIONS = """## Answer format

Reply with a single JSON object and nothing else — no markdown fence, no preamble:

{{
  "answers": {{ {example} }},
  "confidence": 0.0-1.0,
  "reasoning": "one or two sentences explaining the judgment"
}}

Every required field above must appear in "answers", keyed by its exact id.
"confidence" is your own calibrated probability that your answers are correct."""


def assemble_prompt(
    template_schema: dict[str, Any],
    payload: dict[str, Any],
    *,
    guidelines_md: str | None = None,
    variant: dict[str, Any] | None = None,
    prompt_template: str | None = None,
    system: str | None = None,
) -> JudgePrompt:
    """Build the prompt for one unit under one slot's variant.

    ``prompt_template`` is the judge config's versioned prompt (§4). It is treated
    as a *preamble* placed above the rendered task, optionally with ``{task}`` /
    ``{guidelines}`` placeholders for full control — an authoring convenience that
    can never accidentally drop the task itself, because a template that mentions
    neither placeholder simply gets the task appended.
    """
    variant_str = positional_variant(template_schema, variant)
    sections = serialize_display(template_schema, payload, variant_str)
    input_lines, field_ids = serialize_inputs(template_schema)
    example = ", ".join(f'"{fid}": ...' for fid in field_ids) or '"field_id": ...'

    task_parts: list[str] = []
    if sections:
        task_parts.append("## Task\n\n" + "\n\n".join(sections))
    task_parts.append("## Questions\n\n" + "\n".join(input_lines))
    task_parts.append(ANSWER_INSTRUCTIONS.format(example=example))
    task = "\n\n".join(task_parts)

    guidelines_block = (
        f"## Guidelines\n\n{guidelines_md.strip()}" if (guidelines_md or "").strip() else ""
    )

    if prompt_template and ("{task}" in prompt_template or "{guidelines}" in prompt_template):
        user = prompt_template.replace("{guidelines}", guidelines_block).replace("{task}", task)
    else:
        blocks = [b for b in (prompt_template or "").strip().split("\n\n") if b]
        ordered = [*blocks, guidelines_block, task] if blocks else [guidelines_block, task]
        user = "\n\n".join(ordered)
    user = "\n\n".join(part for part in user.split("\n\n") if part.strip())

    return JudgePrompt(system=system or DEFAULT_SYSTEM, user=user, field_ids=field_ids)


def variant_key(template_schema: dict[str, Any], variant: dict[str, Any] | None) -> str:
    """Canonical string form of a slot's variant — the cache key's last component."""
    return positional_variant(template_schema, variant) or ""
