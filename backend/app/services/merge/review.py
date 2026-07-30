"""The human review queue (§7.2) — what a reviewer sees, and what their key press does.

A queue item is deliberately *everything needed to decide in one screen*: the
unit payload, the merged proposal, and every vote behind it with its weight, its
variant and — for judges — its reasoning trace. The reviewer never has to open a
second view to find out why the machine proposed what it proposed, which is the
whole difference between a review queue and a list of unit ids.

Two decisions, ``approve`` and ``override``, writing ``human_approved`` and
``human_override`` respectively (§7.2). Both record the proposal that was on
screen at the time, so an override remains explainable a year later: you can see
what the ensemble said, what the human said instead, and which judges were
wrong. Approving a unit with no proposal at all is refused rather than silently
finalizing an empty label.

``review.queue_backlog`` (§7.3) fires from ``check_backlog`` on the *crossing* of
the threshold: escalations arrive one at a time, so "depth just became the
threshold" is exactly the moment the backlog formed. If a reviewer drains it and
it re-forms, it fires again — which is the useful behaviour, not a bug.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Project, Template, Unit
from app.services.merge.finalize import check_project_completed, final_label_for, finalize_unit
from app.services.merge.merge import merge_unit
from app.services.merge.pipeline import effective_pipeline
from app.services.webhooks import Sender, emit

__all__ = [
    "DEFAULT_BACKLOG_THRESHOLD",
    "ReviewError",
    "backlog_threshold",
    "check_backlog",
    "decide",
    "queue_depth",
    "review_item",
    "review_queue",
]

DEFAULT_BACKLOG_THRESHOLD = 25
DECISIONS = ("approve", "override")


class ReviewError(ValueError):
    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _ensemble_spec(project: Project) -> dict[str, Any]:
    """The pipeline's ensemble stage, so the queue merges the way routing did."""
    for spec in effective_pipeline(project):
        if spec.get("stage") == "ensemble":
            return spec
    return {}


def _proposal(db: Session, unit: Unit, project: Project):
    spec = _ensemble_spec(project)
    judges = spec.get("judges") or None
    kinds = spec.get("kinds") or None
    return merge_unit(
        db,
        unit,
        project,
        method=spec.get("merge") or "calibration_weighted",
        judges=list(judges) if judges else None,
        kinds=tuple(kinds) if kinds else None,
    )


def _queue_query(project_id: int | None):
    stmt = select(Unit).where(Unit.escalated_at.is_not(None), Unit.status != "finalized")
    if project_id is not None:
        stmt = stmt.where(Unit.project_id == project_id)
    # Urgent first, then oldest escalation — the same "priority DESC, age ASC"
    # ordering the assignment engine uses (§6.4), for the same reason.
    return stmt.order_by(Unit.priority.desc(), Unit.escalated_at.asc(), Unit.id.asc())


def queue_depth(db: Session, project_id: int | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(Unit)
        .where(Unit.escalated_at.is_not(None), Unit.status != "finalized")
    )
    if project_id is not None:
        stmt = stmt.where(Unit.project_id == project_id)
    return int(db.scalar(stmt) or 0)


def review_queue(
    db: Session,
    *,
    project_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """The escalated units awaiting a human decision, newest merge included."""
    units = list(db.scalars(_queue_query(project_id).limit(max(1, limit)).offset(max(0, offset))))
    projects: dict[int, Project] = {}
    items = []
    for unit in units:
        project = projects.get(unit.project_id) or db.get(Project, unit.project_id)
        if project is None:  # pragma: no cover - FK makes this unreachable
            continue
        projects[project.id] = project
        items.append(_item(db, unit, project, include_template=False))
    return {
        "project_id": project_id,
        "depth": queue_depth(db, project_id),
        "threshold": backlog_threshold(projects.get(project_id)) if project_id else None,
        "items": items,
    }


def _item(db: Session, unit: Unit, project: Project, *, include_template: bool) -> dict[str, Any]:
    proposal = _proposal(db, unit, project)
    snapshot = unit.quality or {}
    item: dict[str, Any] = {
        "unit_id": unit.id,
        "project_id": project.id,
        "project_name": project.name,
        "batch_id": unit.batch_id,
        "priority": unit.priority,
        "is_gold": unit.is_gold,
        "status": unit.status,
        "escalated_at": unit.escalated_at.isoformat() if unit.escalated_at else None,
        "escalation_reason": snapshot.get("escalation_reason"),
        "failed_keys": snapshot.get("failed_keys") or [],
        "payload": unit.payload,
        "proposal": proposal.as_dict() if proposal else None,
        "consensus_snapshot": {k: v for k, v in snapshot.items() if k != "proposal"},
    }
    if include_template:
        template = db.get(Template, project.template_id)
        item["template"] = (
            {
                "id": template.id,
                "name": template.name,
                "version": template.version,
                "schema": template.schema,
            }
            if template
            else None
        )
        item["guidelines_md"] = project.guidelines_md
    return item


def review_item(db: Session, unit_id: int) -> dict[str, Any]:
    """One queue item plus the template — enough to render the answer widgets."""
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise ReviewError(f"unit {unit_id} not found", status=404)
    project = db.get(Project, unit.project_id)
    if project is None:  # pragma: no cover - FK makes this unreachable
        raise ReviewError(f"project for unit {unit_id} not found", status=404)
    item = _item(db, unit, project, include_template=True)
    final = final_label_for(db, unit_id)
    item["final_label"] = (
        {
            "value": final.value,
            "method": final.method,
            "confidence": final.confidence,
            "decided_by": final.decided_by,
        }
        if final
        else None
    )
    return item


def decide(
    db: Session,
    unit_id: int,
    *,
    decision: str,
    user_id: int | None = None,
    value: dict[str, Any] | None = None,
    comment: str | None = None,
    sender: Sender | None = None,
    sleep: Callable[[float], None] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Approve the merged proposal, or override it with the reviewer's own answer.

    Writes ``final_labels`` with ``method: human_approved | human_override`` and
    provenance carrying the proposal the reviewer was looking at (§7.2).
    """
    if decision not in DECISIONS:
        raise ReviewError(f"decision must be one of {list(DECISIONS)}", status=422)
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise ReviewError(f"unit {unit_id} not found", status=404)
    project = db.get(Project, unit.project_id)
    if project is None:  # pragma: no cover - FK makes this unreachable
        raise ReviewError(f"project for unit {unit_id} not found", status=404)

    proposal = _proposal(db, unit, project)
    if decision == "approve":
        if proposal is None:
            raise ReviewError(
                "nothing to approve: this unit has no labels to merge — override instead",
                status=409,
            )
        final_value = proposal.value
        method = "human_approved"
        confidence = round(proposal.confidence, 6)
    else:
        if not value:
            raise ReviewError("override requires a 'value' object", status=422)
        final_value = value
        method = "human_override"
        # A human override is the ground truth by definition; the ensemble's
        # confidence describes the proposal that was *rejected*, not this answer.
        confidence = 1.0

    provenance: dict[str, Any] = {
        "stage": "human_review",
        "decision": decision,
        "reviewer_user_id": user_id,
        "comment": comment,
        "decided_at": (now or datetime.now(UTC)).isoformat(),
        "proposal": proposal.as_dict() if proposal else None,
    }
    if proposal is not None:
        provenance.update({k: v for k, v in proposal.provenance().items() if k != "merge"})
        provenance["merge"] = proposal.method

    final = finalize_unit(
        db,
        unit,
        value=final_value,
        method=method,
        confidence=confidence,
        provenance=provenance,
        decided_by=user_id,
    )
    fired = check_project_completed(db, project, sender=sender, sleep=sleep)
    return {
        "unit_id": unit.id,
        "decision": decision,
        "method": method,
        "final_label_id": final.id,
        "value": final.value,
        "confidence": final.confidence,
        "queue_depth": queue_depth(db, project.id),
        "webhooks_fired": fired,
    }


# --- backlog webhook (§7.3) ---------------------------------------------------


def backlog_threshold(project: Project | None) -> int:
    if project is None:
        return DEFAULT_BACKLOG_THRESHOLD
    config = project.config or {}
    review = config.get("review") or {}
    raw = review.get("backlog_threshold", config.get("review_backlog_threshold"))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_BACKLOG_THRESHOLD
    return value if value > 0 else DEFAULT_BACKLOG_THRESHOLD


def check_backlog(
    db: Session,
    project: Project,
    *,
    sender: Sender | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """Fire ``review.queue_backlog`` on the escalation that crosses the threshold."""
    threshold = backlog_threshold(project)
    depth = queue_depth(db, project.id)
    if depth != threshold:
        return 0
    kwargs: dict[str, Any] = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    deliveries = emit(
        db,
        "review.queue_backlog",
        project_id=project.id,
        payload={
            "project": project.name,
            "metric": {"queue_depth": depth, "threshold": threshold},
        },
        sender=sender,
        **kwargs,
    )
    return len(deliveries)
