"""Per-unit detail — the drawer behind the M5 unit browser (§11).

Payload preview, each label with its annotator's kind + reputation + variant, the
unit's agreement state and escalation history. This is an admin/reviewer view, so
unlike the annotator-facing submit response it deliberately *does* expose golds,
peer votes and variant identity — the blinding rules in §6.1 protect annotators
mid-task, not admins auditing after the fact.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotator, Label, Project, Slot, Unit
from app.services.quality.consensus import evaluate_unit


def _slot_summary(db: Session, unit_id: int) -> dict[str, int]:
    rows = db.execute(select(Slot.status).where(Slot.unit_id == unit_id)).all()
    counts: dict[str, int] = {}
    for (status,) in rows:
        counts[status] = counts.get(status, 0) + 1
    return counts


def unit_detail(db: Session, unit_id: int) -> dict[str, Any]:
    """Assemble the drawer payload for one unit (§5 GET /units/{id})."""
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise ValueError(f"unit {unit_id} not found")
    project = db.get(Project, unit.project_id)

    labels = list(
        db.scalars(
            select(Label).where(Label.unit_id == unit_id).order_by(Label.submitted_at, Label.id)
        )
    )
    label_rows = []
    for label in labels:
        annotator = db.get(Annotator, label.annotator_id)
        slot = db.get(Slot, label.slot_id)
        label_rows.append(
            {
                "label_id": label.id,
                "slot_id": label.slot_id,
                "annotator_id": label.annotator_id,
                "annotator_kind": annotator.kind if annotator else None,
                "annotator_name": annotator.display_name if annotator else None,
                "reputation": round(annotator.reputation_score, 4) if annotator else None,
                "variant": slot.variant if slot else None,
                "raw": label.raw,
                "value": label.value,
                "confidence": label.confidence,
                "is_valid": label.is_valid,
                "submitted_at": label.submitted_at.isoformat() if label.submitted_at else None,
            }
        )

    # Live consensus recompute so the drawer is correct even on pre-M4 units; the
    # cached snapshot (with escalation_reason) is included when present.
    consensus = evaluate_unit(db, unit, project).as_dict() if project else None

    return {
        "unit_id": unit.id,
        "project_id": unit.project_id,
        "batch_id": unit.batch_id,
        "status": unit.status,
        "priority": unit.priority,
        "is_gold": unit.is_gold,
        "gold_expected": unit.gold_expected,
        "escalated_at": unit.escalated_at.isoformat() if unit.escalated_at else None,
        "payload": unit.payload,
        "slots": _slot_summary(db, unit_id),
        "labels": label_rows,
        "consensus": consensus,
        "quality_snapshot": unit.quality,
    }
