"""Writing ``final_labels`` — the decided answer, with provenance (§4, §7.2).

One row per unit, updated in place rather than appended to. The alternative —
keeping every decision as a new row and reading "the latest" — sounds like better
history until you write the third query that has to remember the ``ORDER BY``, or
the export that quietly emits two rows for one unit. History that matters is
already kept: the labels are immutable, and ``provenance`` on the row records the
decision that produced it (including, on an override, the proposal the reviewer
rejected). So the table answers exactly one question — *what is this unit's
label?* — and answers it with one row.

``project.completed`` (§7.3) fires from here because this is the only place a
project can *become* complete. It fires once per completion: the check is
"nothing unfinalized remains, and we have not already announced it", where
"already announced" reads the ``webhook_deliveries`` audit trail rather than a
new flag column — the event is only interesting if somebody subscribed, and if
somebody subscribed the delivery row exists.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import FinalLabel, Project, Unit, WebhookDelivery
from app.services.webhooks import Sender, emit

__all__ = [
    "final_label_for",
    "finalize_unit",
    "unfinalized_count",
    "check_project_completed",
]


def final_label_for(db: Session, unit_id: int) -> FinalLabel | None:
    return db.scalar(select(FinalLabel).where(FinalLabel.unit_id == unit_id).limit(1))


def finalize_unit(
    db: Session,
    unit: Unit,
    *,
    value: dict[str, Any],
    method: str,
    confidence: float | None = None,
    provenance: dict[str, Any] | None = None,
    decided_by: int | None = None,
) -> FinalLabel:
    """Write (or replace) a unit's final label and mark the unit finalized."""
    final = final_label_for(db, unit.id)
    if final is None:
        final = FinalLabel(unit_id=unit.id)
        db.add(final)
    final.value = value
    final.confidence = confidence
    final.method = method
    final.provenance = provenance
    final.decided_by = decided_by
    unit.status = "finalized"
    # A finalized unit is out of review: leaving ``escalated_at`` set would keep
    # it in the queue forever, which is how review backlogs become fiction.
    unit.escalated_at = None
    db.flush()
    return final


def unfinalized_count(db: Session, project_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Unit)
            .where(Unit.project_id == project_id, Unit.status != "finalized")
        )
        or 0
    )


def _already_announced(db: Session, project_id: int) -> bool:
    return (
        db.scalar(
            select(WebhookDelivery.id)
            .where(
                WebhookDelivery.event == "project.completed",
                WebhookDelivery.project_id == project_id,
            )
            .limit(1)
        )
        is not None
    )


def check_project_completed(
    db: Session,
    project: Project,
    *,
    sender: Sender | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """Fire ``project.completed`` (§7.3) if every unit is finalized. Returns deliveries."""
    total = int(
        db.scalar(select(func.count()).select_from(Unit).where(Unit.project_id == project.id)) or 0
    )
    if total == 0 or unfinalized_count(db, project.id) > 0:
        return 0
    if _already_announced(db, project.id):
        return 0
    kwargs: dict[str, Any] = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    deliveries = emit(
        db,
        "project.completed",
        project_id=project.id,
        payload={"project": project.name, "metric": {"units": total, "unfinalized": 0}},
        sender=sender,
        **kwargs,
    )
    return len(deliveries)
