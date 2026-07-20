"""Analytics endpoints (§5). M4 ships the agreement half (§6.3); bias, costs and
progress arrive with M5/M7.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_reviewer
from app.db import get_db
from app.models import Project, Unit, User
from app.services.quality import project_agreement
from app.services.quality.consensus import evaluate_unit

router = APIRouter(prefix="/projects", tags=["analytics"])

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
