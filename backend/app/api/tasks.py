"""Assignment endpoints (§5): next / submit / skip.

All are annotator-gated (rank-inclusive, so reviewers/admins may also call them;
judge workers authenticate as ``role=annotator`` service users). A human token
may only act as its own annotator record; admins may act as any.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import require_annotator
from app.db import get_db
from app.models import Annotator, Unit, User
from app.schemas.api import LabelOut, SubmitRequest, TaskOut
from app.services.assignment import (
    AssignmentError,
    available_work,
    next_task,
    skip_task,
    submit_label,
)
from app.services.quality import QualityOutcome

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _blind_quality(outcome: QualityOutcome | None) -> dict | None:
    """What an annotator may learn about their own submission (§6.1).

    Withheld: whether the unit was a gold and whether they passed it (golds must
    stay indistinguishable), and the consensus block (their peers' votes).
    """
    if outcome is None:
        return None
    return {
        "paused": outcome.paused,
        "labels_voided": outcome.labels_voided,
        "reputation": outcome.reputation,
        "flags": outcome.flags,
    }


def _authorize_annotator(db: Session, user: User, annotator_id: int) -> Annotator:
    """Ensure the caller may act as this annotator (§5 auth)."""
    annotator = db.get(Annotator, annotator_id)
    if annotator is None:
        raise HTTPException(status_code=404, detail="annotator not found")
    # Humans may act only as themselves; admins may act as anyone. Model judges
    # are driven by annotator-role service users, so any annotator token passes.
    if annotator.kind == "human" and user.role != "admin" and annotator.user_id != user.id:
        raise HTTPException(status_code=403, detail="cannot act as another annotator")
    return annotator


@router.get("/available")
def get_available(
    annotator: int = Query(description="Annotator id to list available work for."),
    user: User = Depends(require_annotator),
    db: Session = Depends(get_db),
) -> dict:
    """Per-project available work for an annotator — the landing page (§11, M5).

    Counts the open slots this annotator is still eligible for in each project
    (same exclusion the assignment engine applies), so they can pick where to
    label. Authorized like the other task calls: a human may list only their own
    work; admins may list anyone's."""
    _authorize_annotator(db, user, annotator)
    try:
        projects = available_work(db, annotator)
    except AssignmentError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    return {"annotator_id": annotator, "projects": projects}


@router.get("/next")
def get_next(
    annotator: int = Query(description="Annotator id requesting work."),
    project: int = Query(description="Project to pull a task from."),
    user: User = Depends(require_annotator),
    db: Session = Depends(get_db),
):
    """Lease and return the next task, or 204 when the queue is empty."""
    _authorize_annotator(db, user, annotator)
    try:
        slot = next_task(db, annotator, project)
    except AssignmentError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    if slot is None:
        return Response(status_code=204)
    unit = db.get(Unit, slot.unit_id)
    return TaskOut(
        slot_id=slot.id,
        unit_id=slot.unit_id,
        project_id=project,
        payload=unit.payload if unit else {},
        variant=slot.variant,
        lease_expires_at=slot.lease_expires_at,
    )


@router.post("/{slot_id:int}/submit", response_model=LabelOut, status_code=201)
def post_submit(
    slot_id: int,
    body: SubmitRequest,
    annotator: int = Query(description="Annotator submitting the label."),
    user: User = Depends(require_annotator),
    db: Session = Depends(get_db),
):
    """Submit a label for a held slot (validated, canonicalized §2.8).

    ``value`` is recomputed server-side by the quality pipeline (§2.6); anything
    the client sent is advisory. The response echoes a *blinded* quality summary
    (§6.1): the annotator learns they were paused, but never whether the unit was
    a gold they got wrong, and never their peers' votes.
    """
    _authorize_annotator(db, user, annotator)
    try:
        label = submit_label(
            db,
            slot_id,
            annotator,
            raw=body.raw,
            value=body.value,
            confidence=body.confidence,
            reasoning=body.reasoning,
            comment=body.comment,
            latency_ms=body.latency_ms,
        )
    except AssignmentError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e

    outcome: QualityOutcome | None = getattr(label, "quality", None)
    return LabelOut(
        id=label.id,
        slot_id=label.slot_id,
        unit_id=label.unit_id,
        annotator_id=label.annotator_id,
        value=label.value,
        is_valid=label.is_valid,
        quality=_blind_quality(outcome),
    )


@router.post("/{slot_id:int}/skip", status_code=200)
def post_skip(
    slot_id: int,
    annotator: int = Query(description="Annotator releasing the lease."),
    user: User = Depends(require_annotator),
    db: Session = Depends(get_db),
) -> dict:
    """Release a held lease; the slot reopens with its variant retained (§2.7)."""
    _authorize_annotator(db, user, annotator)
    try:
        slot = skip_task(db, slot_id, annotator)
    except AssignmentError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    return {"slot_id": slot.id, "status": slot.status}
