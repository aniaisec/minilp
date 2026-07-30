"""Review queue + routing endpoints (§5, §7.2) — reviewer-role gated.

``require_reviewer`` is rank-inclusive (§5): reviewers and admins pass, plain
annotators get a 403. That gate is the whole authorization story here — a
reviewer may see every escalated unit, including golds, peer votes and variant
identity, because the §6.1 blinding rules protect annotators *mid-task*, not
people auditing after the fact (the same reasoning as the M5 unit drawer).

``/projects/{id}/route`` is the backfill: re-run routing over every unit that has
stopped collecting. It exists because a pipeline is a *setting* — change it and
you want the change applied to the units already sitting in the project, not only
to the ones labeled after the edit.
"""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_reviewer
from app.db import get_db
from app.models import Project, Unit, User
from app.schemas.api import PipelineOut, PipelineUpdate, ReviewDecision
from app.services.merge import (
    PipelineError,
    ReviewError,
    backlog_threshold,
    decide,
    effective_pipeline,
    queue_depth,
    registered_stages,
    review_item,
    review_queue,
    route_unit,
    validate_pipeline,
)
from app.services.merge.pipeline import CONDITION_VARIABLES

router = APIRouter(tags=["review"])


# --- the queue ----------------------------------------------------------------


@router.get("/review/queue")
def get_queue(
    project: int | None = Query(default=None, description="Restrict to one project."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> dict:
    """Escalated units awaiting a human decision, merged proposal included (§7.2).

    Ordered ``priority DESC, escalated_at ASC`` — urgent first, then oldest, the
    same ordering the assignment engine uses for open slots (§6.4).
    """
    return review_queue(db, project_id=project, limit=limit, offset=offset)


@router.get("/review/depth")
def get_depth(
    project: int | None = Query(default=None),
    _user: User = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> dict:
    """Queue depth and the threshold that would fire ``review.queue_backlog``."""
    proj = db.get(Project, project) if project is not None else None
    return {
        "project_id": project,
        "depth": queue_depth(db, project),
        "threshold": backlog_threshold(proj),
    }


@router.get("/review/{unit_id:int}")
def get_item(
    unit_id: int,
    _user: User = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> dict:
    """One queue item with its template — enough to render the answer widgets."""
    try:
        return review_item(db, unit_id)
    except ReviewError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e


@router.post("/review/{unit_id:int}:decide", status_code=200)
def post_decide(
    unit_id: int,
    body: ReviewDecision,
    user: User = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> dict:
    """Approve the merged proposal, or override it (§7.2).

    Writes ``final_labels`` with ``method: human_approved | human_override`` and
    provenance carrying the proposal that was on screen — so an override stays
    explainable long after the judges' weights have moved.
    """
    try:
        return decide(
            db,
            unit_id,
            decision=body.decision,
            user_id=user.id,
            value=body.value,
            comment=body.comment,
        )
    except ReviewError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e


# --- the pipeline itself ------------------------------------------------------


@router.get("/projects/{project_id:int}/pipeline", response_model=PipelineOut)
def get_pipeline(
    project_id: int,
    _user: User = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> dict:
    """The project's routing policy, resolved — the default when it has none."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return {
        "project_id": project.id,
        "pipeline": effective_pipeline(project),
        "is_default": not project.pipeline,
        "stages": registered_stages(),
        "variables": sorted(CONDITION_VARIABLES),
    }


@router.put("/projects/{project_id:int}/pipeline", response_model=PipelineOut)
def put_pipeline(
    project_id: int,
    body: PipelineUpdate,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Replace the routing policy. Validated at save time (§7.2) — a bad stage
    name or an unparseable condition is a 422 here, not a rule that never fires.

    Sending ``null`` resets the project to the shipped default.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        validated = validate_pipeline(body.pipeline)
    except PipelineError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    project.pipeline = validated or None
    db.flush()
    return {
        "project_id": project.id,
        "pipeline": effective_pipeline(project),
        "is_default": not project.pipeline,
        "stages": registered_stages(),
        "variables": sorted(CONDITION_VARIABLES),
    }


@router.post("/projects/{project_id:int}/route")
def post_route(
    project_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Re-run routing over the project's already-collected units (backfill).

    Only units that have stopped collecting are considered (``labeled`` and,
    with ``include_finalized``, ones an earlier automatic pass already decided).
    A unit a *human* decided is never re-decided — ``route_unit`` refuses.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    statuses = ["labeled"]
    if body.get("include_finalized"):
        statuses.append("finalized")
    units = list(
        db.scalars(
            select(Unit)
            .where(Unit.project_id == project_id, Unit.status.in_(statuses))
            .order_by(Unit.id)
        )
    )
    counts = {"auto_finalized": 0, "escalated": 0, "skipped": 0, "none": 0}
    webhooks = 0
    for unit in units:
        result = route_unit(db, unit, project)
        counts[result.decision] = counts.get(result.decision, 0) + 1
        webhooks += result.webhooks_fired
    return {
        "project_id": project_id,
        "units_considered": len(units),
        "webhooks_fired": webhooks,
        **counts,
    }
