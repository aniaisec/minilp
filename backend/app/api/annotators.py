"""Annotator quality endpoints (§5, §6.2).

``GET /annotators/{id}/report`` is readable by the annotator themselves — an
annotator who has been paused must be able to see *why* without an admin in the
loop, and the annotation UI reads it to render the reputation badge. Resuming is
admin-only.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_annotator
from app.db import get_db
from app.models import Annotator, User
from app.schemas.api import AnnotatorOut
from app.services.quality import annotator_report, refresh_reputation, resume_annotator

router = APIRouter(prefix="/annotators", tags=["annotators"])


def _authorize_self_or_admin(db: Session, user: User, annotator_id: int) -> Annotator:
    annotator = db.get(Annotator, annotator_id)
    if annotator is None:
        raise HTTPException(status_code=404, detail="annotator not found")
    if user.role == "admin" or user.role == "reviewer":
        return annotator
    if annotator.kind == "human" and annotator.user_id == user.id:
        return annotator
    raise HTTPException(status_code=403, detail="cannot read another annotator's report")


@router.get("/{annotator_id:int}/report")
def get_report(
    annotator_id: int,
    project: int | None = Query(
        default=None, description="Scope gold accuracy and agreement to one project."
    ),
    user: User = Depends(require_annotator),
    db: Session = Depends(get_db),
) -> dict:
    """Reputation/calibration history, gold accuracy, and bias (§5)."""
    _authorize_self_or_admin(db, user, annotator_id)
    return annotator_report(db, annotator_id, project_id=project)


@router.post("/{annotator_id:int}:resume", response_model=AnnotatorOut)
def post_resume(
    annotator_id: int,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Annotator:
    """Lift a quality pause (§6.1). Already-voided work stays voided."""
    annotator = resume_annotator(db, annotator_id)
    if annotator is None:
        raise HTTPException(status_code=404, detail="annotator not found")
    refresh_reputation(db, annotator_id)
    return annotator


@router.post("/{annotator_id:int}:recompute", response_model=AnnotatorOut)
def post_recompute(
    annotator_id: int,
    project: int | None = Query(default=None),
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Annotator:
    """Force a reputation recompute (after a config change, or for a backfill)."""
    annotator = db.get(Annotator, annotator_id)
    if annotator is None:
        raise HTTPException(status_code=404, detail="annotator not found")
    refresh_reputation(db, annotator_id, project_id=project)
    return annotator
