"""JSONL exports (§10).

Four formats, all one JSON object per line, all derived from the same place —
valid labels plus the per-key consensus the quality subsystem already computes
(§6.4). Nothing here re-decides what a unit's answer is; it reads the winner
consensus picked, so an export and the progress view can never disagree.

    labels      one row per unit: payload, final label per key, per-label
                provenance. The general-purpose format, and the one that
                **re-imports** through ``units:bulk`` unchanged (§10) — a row
                carries ``payload`` / ``is_gold`` / ``gold_expected`` / ``priority``
                exactly where ingest looks for them, so a project can be exported
                and rebuilt without a transformation step.
    raw         one row per *label*, with raw + canonical + variant + annotator
                provenance. The bias-study format (§9): it is the only one that
                preserves which side was clicked as well as which item won.
    preference  RLHF-ready pairs for variant-bearing comparison projects:
                {prompt, chosen, rejected, meta:{…}}.
    sft         {input, output} pairs from generation-style templates (a free-text
                input is the output; the first text/markdown block is the input).

Rows are produced lazily so a large project streams rather than materializing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotator, Label, Project, Slot, Template, Unit
from app.services.merge.finalize import final_label_for
from app.services.quality.canonical import positional_variant
from app.services.quality.consensus import evaluate_unit
from app.services.templates.spec import UNIT_REF_PREFIX

EXPORT_FORMATS = ("labels", "raw", "preference", "sft")


class ExportError(ValueError):
    """The requested export cannot be produced for this project."""


# --- shared helpers ---------------------------------------------------------


def _ref_key(source: str) -> str:
    return source[len(UNIT_REF_PREFIX) :] if source.startswith(UNIT_REF_PREFIX) else source


def _project_and_template(db: Session, project_id: int) -> tuple[Project, Template]:
    project = db.get(Project, project_id)
    if project is None:
        raise ExportError(f"project {project_id} not found")
    template = db.get(Template, project.template_id)
    if template is None:
        raise ExportError(f"project {project_id} references missing template")
    return project, template


def _units(db: Session, project_id: int) -> Iterator[Unit]:
    yield from db.scalars(select(Unit).where(Unit.project_id == project_id).order_by(Unit.id))


def _valid_labels(db: Session, unit_id: int) -> list[Label]:
    return list(
        db.scalars(
            select(Label)
            .where(Label.unit_id == unit_id, Label.is_valid.is_(True))
            .order_by(Label.submitted_at, Label.id)
        )
    )


def _annotator_meta(
    db: Session, label: Label, cache: dict[int, Annotator | None]
) -> dict[str, Any]:
    if label.annotator_id not in cache:
        cache[label.annotator_id] = db.get(Annotator, label.annotator_id)
    annotator = cache[label.annotator_id]
    return {
        "annotator_id": label.annotator_id,
        "annotator_kind": annotator.kind if annotator else None,
        "reputation": round(annotator.reputation_score, 4) if annotator else None,
    }


def _slot_variant(
    db: Session, label: Label, cache: dict[int, Slot | None]
) -> dict[str, Any] | None:
    if label.slot_id not in cache:
        cache[label.slot_id] = db.get(Slot, label.slot_id)
    slot = cache[label.slot_id]
    return slot.variant if slot else None


def _mean(values: list[float]) -> float | None:
    numbers = [v for v in values if v is not None]
    return round(sum(numbers) / len(numbers), 4) if numbers else None


# --- labels -----------------------------------------------------------------


def _labels_rows(db: Session, project: Project, template: Template) -> Iterator[dict[str, Any]]:
    ann_cache: dict[int, Annotator | None] = {}
    slot_cache: dict[int, Slot | None] = {}
    for unit in _units(db, project.id):
        labels = _valid_labels(db, unit.id)
        consensus = evaluate_unit(db, unit, project)
        # The decided row (§7.2) wins when it exists — it is what a human review
        # may have overridden, and a training export must not silently prefer
        # the ensemble's rejected proposal over what a reviewer actually decided.
        # A unit still collecting has no ``final_labels`` row yet, so consensus
        # (this export's original source) is the correct fallback, not an error.
        final = final_label_for(db, unit.id)
        if final is not None:
            final_label = final.value or {}
            final_method: str | None = final.method
            final_confidence: float | None = final.confidence
        else:
            final_label = {k.key: k.winner for k in consensus.keys if k.agreed}
            final_method = None
            final_confidence = None
        row: dict[str, Any] = {
            # --- re-import surface: exactly the keys units:bulk reads ---
            "payload": unit.payload,
            "priority": unit.priority,
            "is_gold": unit.is_gold,
            # --- export payload ---
            "unit_id": unit.id,
            "project_id": project.id,
            "batch_id": unit.batch_id,
            "status": unit.status,
            "escalated": unit.escalated_at is not None,
            "template": {"id": template.id, "name": template.name, "version": template.version},
            "final_label": final_label,
            "final_method": final_method,
            "final_confidence": final_confidence,
            "consensus": {
                k.key: {"winner": k.winner, "support": k.support, "votes": k.votes, "rate": k.rate}
                for k in consensus.keys
            },
            "labels": [
                {
                    **_annotator_meta(db, label, ann_cache),
                    "variant": _slot_variant(db, label, slot_cache),
                    "value": label.value,
                    "confidence": label.confidence,
                    "cost_usd": label.cost_usd,
                    "submitted_at": label.submitted_at.isoformat() if label.submitted_at else None,
                }
                for label in labels
            ],
        }
        if unit.gold_expected is not None:
            row["gold_expected"] = unit.gold_expected
        yield row


# --- raw --------------------------------------------------------------------


def _raw_rows(db: Session, project: Project, template: Template) -> Iterator[dict[str, Any]]:
    ann_cache: dict[int, Annotator | None] = {}
    slot_cache: dict[int, Slot | None] = {}
    for unit in _units(db, project.id):
        # Voided labels are included with ``is_valid: false`` — a bias study wants
        # to know a rater was removed, not to have their rows silently vanish.
        labels = list(
            db.scalars(
                select(Label).where(Label.unit_id == unit.id).order_by(Label.submitted_at, Label.id)
            )
        )
        for label in labels:
            variant = _slot_variant(db, label, slot_cache)
            yield {
                "label_id": label.id,
                "unit_id": unit.id,
                "project_id": project.id,
                "slot_id": label.slot_id,
                "payload": unit.payload,
                "is_gold": unit.is_gold,
                "gold_passed": label.gold_passed,
                "raw": label.raw,
                "value": label.value,
                "variant": variant,
                "variant_value": positional_variant(template.schema, variant),
                **_annotator_meta(db, label, ann_cache),
                "confidence": label.confidence,
                "reasoning": label.reasoning,
                "comment": label.comment,
                "latency_ms": label.latency_ms,
                "tokens_in": label.tokens_in,
                "tokens_out": label.tokens_out,
                "cost_usd": label.cost_usd,
                "cache_hit": label.cache_hit,
                "is_valid": label.is_valid,
                "submitted_at": label.submitted_at.isoformat() if label.submitted_at else None,
            }


# --- preference (RLHF) ------------------------------------------------------


def _panel_sources(schema: dict[str, Any]) -> list[str]:
    """Payload keys behind a ``panel_group``'s panels, in canonical item order."""
    for block in schema.get("display", []) or []:
        if block.get("type") == "panel_group":
            return [_ref_key(s) for s in (block.get("sources") or [])]
    return []


def _prompt_source(schema: dict[str, Any]) -> str | None:
    """The first non-panel text/markdown block — the shared prompt."""
    for block in schema.get("display", []) or []:
        if block.get("type") in ("text", "markdown") and block.get("source"):
            return _ref_key(block["source"])
    return None


def _comparison_key(schema: dict[str, Any]) -> str | None:
    for field in schema.get("inputs", []) or []:
        if field.get("type") == "choice_buttons":
            return field.get("id")
    return None


def _preference_rows(db: Session, project: Project, template: Template) -> Iterator[dict[str, Any]]:
    schema = template.schema
    key = _comparison_key(schema)
    panels = _panel_sources(schema)
    if not key or len(panels) < 2:
        raise ExportError(
            "preference export needs a comparison template: a panel_group with at "
            "least two sources and a choice_buttons input "
            f"(template '{template.name}' has neither)"
        )
    prompt_key = _prompt_source(schema)
    items = [chr(ord("A") + i) for i in range(len(panels))]  # A, B, …
    ann_cache: dict[int, Annotator | None] = {}
    slot_cache: dict[int, Slot | None] = {}

    for unit in _units(db, project.id):
        labels = _valid_labels(db, unit.id)
        if not labels:
            continue
        votes: dict[str, int] = {item: 0 for item in items}
        ties = 0
        by_variant: dict[str, list[Any]] = {}
        reputations: list[float] = []
        for label in labels:
            value = (label.value or {}).get(key)
            if value in votes:
                votes[value] += 1
            else:
                ties += 1
            variant = positional_variant(schema, _slot_variant(db, label, slot_cache))
            if variant:
                by_variant.setdefault(variant, []).append(value)
            meta = _annotator_meta(db, label, ann_cache)
            if meta["reputation"] is not None:
                reputations.append(meta["reputation"])

        ranked = sorted(votes.items(), key=lambda kv: -kv[1])
        winner, win_votes = ranked[0]
        runner_up, runner_votes = ranked[1]
        # A unit with no majority (or an outright tie) is not a preference pair.
        if win_votes == 0 or win_votes == runner_votes:
            continue

        # Order-flip rate: did the winner differ between presentation orders?
        per_variant_winner = {
            variant: max(set(vals), key=vals.count) for variant, vals in by_variant.items() if vals
        }
        distinct = {w for w in per_variant_winner.values()}
        flip_rate = 0.0 if len(distinct) <= 1 else 1.0

        yield {
            "unit_id": unit.id,
            "prompt": unit.payload.get(prompt_key) if prompt_key else None,
            "chosen": unit.payload.get(panels[items.index(winner)]),
            "rejected": unit.payload.get(panels[items.index(runner_up)]),
            "meta": {
                "votes_a": votes.get("A", 0),
                "votes_b": votes.get("B", 0),
                "ties": ties,
                "order_flip_rate": flip_rate,
                "mean_annotator_reputation": _mean(reputations),
                "human_reviewed": unit.escalated_at is not None,
            },
        }


# --- sft --------------------------------------------------------------------


def _free_text_key(schema: dict[str, Any]) -> str | None:
    for field in schema.get("inputs", []) or []:
        if field.get("type") == "free_text":
            return field.get("id")
    return None


def _sft_rows(db: Session, project: Project, template: Template) -> Iterator[dict[str, Any]]:
    schema = template.schema
    key = _free_text_key(schema)
    if not key:
        raise ExportError(
            "sft export needs a generation-style template with a free_text input "
            f"(template '{template.name}' has none)"
        )
    input_key = _prompt_source(schema)
    for unit in _units(db, project.id):
        for label in _valid_labels(db, unit.id):
            output = (label.value or {}).get(key)
            if not isinstance(output, str) or not output.strip():
                continue
            yield {
                "unit_id": unit.id,
                "input": unit.payload.get(input_key) if input_key else unit.payload,
                "output": output,
            }


# --- dispatch ---------------------------------------------------------------

_BUILDERS = {
    "labels": _labels_rows,
    "raw": _raw_rows,
    "preference": _preference_rows,
    "sft": _sft_rows,
}


def export_rows(db: Session, project_id: int, fmt: str) -> Iterator[dict[str, Any]]:
    """Yield the export rows for a project in ``fmt`` (§10)."""
    if fmt not in EXPORT_FORMATS:
        raise ExportError(f"unknown export format '{fmt}' (expected one of {list(EXPORT_FORMATS)})")
    project, template = _project_and_template(db, project_id)
    return _BUILDERS[fmt](db, project, template)


def iter_jsonl(db: Session, project_id: int, fmt: str) -> Iterator[str]:
    """The same rows, serialized one JSON object per line."""
    for row in export_rows(db, project_id, fmt):
        yield json.dumps(row, default=str, ensure_ascii=False) + "\n"
