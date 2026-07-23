"""Per-project annotator roster — the admin dashboard's annotator table (§11).

Everyone who has landed a label on the project, with their kind, live reputation,
pause state, label volume and rolling gold accuracy. Kept scoped to the project so
one annotator's numbers reflect the project being viewed, matching how
``/annotators/{id}/report?project=`` scopes gold accuracy and agreement.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Annotator, Label, Project, Unit
from app.services.quality.reputation import gold_accuracy


def project_roster(db: Session, project_id: int) -> dict[str, Any]:
    if db.get(Project, project_id) is None:
        raise ValueError(f"project {project_id} not found")

    # Label volume (valid) and voided counts per annotator, in one pass each.
    valid = dict(
        db.execute(
            select(Label.annotator_id, func.count())
            .join(Unit, Label.unit_id == Unit.id)
            .where(Unit.project_id == project_id, Label.is_valid.is_(True))
            .group_by(Label.annotator_id)
        ).all()
    )
    voided = dict(
        db.execute(
            select(Label.annotator_id, func.count())
            .join(Unit, Label.unit_id == Unit.id)
            .where(Unit.project_id == project_id, Label.is_valid.is_(False))
            .group_by(Label.annotator_id)
        ).all()
    )

    ids = set(valid) | set(voided)
    rows = []
    for aid in sorted(ids):
        annotator = db.get(Annotator, aid)
        if annotator is None:
            continue
        passes, total = gold_accuracy(db, aid, project_id=project_id)
        rows.append(
            {
                "annotator_id": aid,
                "kind": annotator.kind,
                "display_name": annotator.display_name,
                "status": annotator.status,
                "pause_reason": annotator.pause_reason,
                "reputation": round(annotator.reputation_score, 4),
                "labels_valid": valid.get(aid, 0),
                "labels_voided": voided.get(aid, 0),
                "gold_passes": passes,
                "gold_total": total,
                "gold_accuracy": round(passes / total, 4) if total else None,
            }
        )
    return {"project_id": project_id, "annotators": rows, "count": len(rows)}
