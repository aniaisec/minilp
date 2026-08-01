"""Active-learning endpoints (§5, §8, M9) — batch selection, checkpoint
re-enrollment, the iteration eval curve.

Reviewer-gated for the two read endpoints, same bucket as costs and progress
(§5): deciding what the next labeling round should prioritize is a reviewer
call. Registering a checkpoint is admin-gated like every other judge-config
write (§7.1) — it is a decision to enroll a rater and, for a paid provider, to
spend money.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_reviewer
from app.db import get_db
from app.models import User
from app.schemas.api import CheckpointRegister
from app.services.active_learning import iteration_curve, rank_batch, register_checkpoint
from app.services.judges import JudgeError

router = APIRouter(prefix="/projects/{project_id:int}/active-learning", tags=["active-learning"])


def _judge_error(e: JudgeError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=str(e))


@router.get("/batch")
def get_batch(
    project_id: int,
    limit: int = Query(default=20, ge=1, le=500),
    judge_config_id: int | None = Query(
        default=None, description="Whose confidence to weigh in — the current student model."
    ),
    dedupe_field: str | None = Query(
        default=None, description="Payload key holding a numeric embedding vector."
    ),
    dedupe_threshold: float = Query(default=0.85, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_reviewer),
) -> dict:
    """Next most-informative units — ensemble disagreement, entropy, and
    (with ``judge_config_id``) the student model's own low confidence (§8)."""
    try:
        return rank_batch(
            db,
            project_id,
            limit=limit,
            judge_config_id=judge_config_id,
            dedupe_field=dedupe_field,
            dedupe_threshold=dedupe_threshold,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/checkpoints:register")
def post_register_checkpoint(
    project_id: int,
    body: CheckpointRegister,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    """Version + attach in one call — the "re-enroll" step of the loop (§8)."""
    try:
        return register_checkpoint(db, project_id, **body.model_dump())
    except JudgeError as e:
        raise _judge_error(e) from e


@router.get("/iterations")
def get_iterations(
    project_id: int,
    name: str = Query(..., description="Judge config name — the student model's version line."),
    db: Session = Depends(get_db),
    _user: User = Depends(require_reviewer),
) -> dict:
    """The eval curve across a checkpoint line's versions (§8 steps 4-5)."""
    try:
        return iteration_curve(db, project_id, name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
