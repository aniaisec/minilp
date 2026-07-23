"""Analytics endpoints (§5). M4 shipped the agreement half (§6.3); M5 adds
progress (§11), variant-bias (§9) and label distribution. Judge costs arrive with
M7.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_reviewer
from app.db import get_db
from app.models import Project, Unit, User
from app.services.analytics import (
    project_bias,
    project_distribution,
    project_progress,
)
from app.services.quality import project_agreement
from app.services.quality.consensus import evaluate_unit

router = APIRouter(prefix="/projects", tags=["analytics"])


@router.get("/{project_id:int}/progress")
def get_progress(
    project_id: int,
    window_hours: float = Query(
        default=24.0, gt=0, description="Trailing window for the throughput/ETA rate."
    ),
    _user: User = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> dict:
    """Status funnel, per-batch and per-variant fill, per-key consensus rates,
    throughput and ETA (§5, §11)."""
    try:
        return project_progress(db, project_id, window_hours=window_hours)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{project_id:int}/analytics/bias")
def get_bias(
    project_id: int,
    _user: User = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> dict:
    """Variant/order-bias metrics with CIs — humans and judges separately (§9)."""
    try:
        return project_bias(db, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{project_id:int}/analytics/distribution")
def get_distribution(
    project_id: int,
    _user: User = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> dict:
    """Per-key canonical-answer distribution, overall and by annotator kind (§11)."""
    try:
        return project_distribution(db, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


_GROUPS = ("all", "human", "model", "cross")


@router.get("/{project_id:int}/analytics/agreement")
def get_agreement(
    project_id: int,
    group: str = Query(
        default="all",
        description="all | human | model | cross (human majority vs judge majority).",
    ),
    _user: User = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> dict:
    """Per-key kappa and mean per-unit entropy (§6.3)."""
    if group not in _GROUPS:
        raise HTTPException(status_code=422, detail=f"group must be one of {list(_GROUPS)}")
    try:
        return project_agreement(db, project_id, group=group)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{project_id:int}/consensus")
def get_consensus(
    project_id: int,
    escalated: bool | None = Query(
        default=None, description="Filter to units escalated for review (or not)."
    ),
    _user: User = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> dict:
    """Per-unit consensus state — the drill-down behind the M5 unit browser.

    Reads each unit's cached ``quality`` snapshot where present and recomputes on
    the fly otherwise, so the endpoint is correct on units labeled before M4.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    stmt = select(Unit).where(Unit.project_id == project_id)
    if escalated is True:
        stmt = stmt.where(Unit.escalated_at.is_not(None))
    elif escalated is False:
        stmt = stmt.where(Unit.escalated_at.is_(None))

    units = []
    for unit in db.scalars(stmt.order_by(Unit.id)):
        snapshot = unit.quality or evaluate_unit(db, unit, project).as_dict()
        units.append(
            {
                "unit_id": unit.id,
                "status": unit.status,
                "is_gold": unit.is_gold,
                "escalated_at": unit.escalated_at.isoformat() if unit.escalated_at else None,
                "consensus": snapshot,
            }
        )
    return {"project_id": project_id, "units": units, "count": len(units)}
