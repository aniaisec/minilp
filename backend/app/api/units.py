"""Unit-level admin operations (§5): adjust priority, void/requeue."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_reviewer
from app.db import get_db
from app.models import Unit, User
from app.schemas.api import UnitOut, UnitPatch
from app.services.analytics import unit_detail
from app.services.assignment import void_unit

router = APIRouter(prefix="/units", tags=["units"])


@router.get("/{unit_id:int}")
def get_unit_detail(
    unit_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_reviewer),
) -> dict:
    """Per-unit detail drawer: payload, per-label annotator/reputation/variant,
    consensus and escalation state (§11). Reviewer/admin only — this view is not
    blinded (§6.1 protects annotators mid-task, not auditors)."""
    try:
        return unit_detail(db, unit_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.patch("/{unit_id:int}", response_model=UnitOut)
def patch_unit(
    unit_id: int,
    body: UnitPatch,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> Unit:
    """Adjust priority and/or void+requeue a unit (§5, §6.4).

    Voiding invalidates the unit's valid labels and reopens its filled slots with
    variant retained, so the unit re-enters the pool in balance.
    """
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="unit not found")
    if body.priority is not None:
        unit.priority = body.priority
    if body.void:
        void_unit(db, unit_id)
    db.flush()
    db.refresh(unit)
    return unit
