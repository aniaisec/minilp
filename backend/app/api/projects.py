"""Project + unit-ingest endpoints (§5)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Project, Unit
from app.schemas.api import (
    BulkIngestRequest,
    ProjectCreate,
    ProjectOut,
    UnitOut,
)
from app.services.ingest.bulk import ingest_report, ingest_units, parse_jsonl
from app.services.projects import ProjectError, create_project

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
def post_project(body: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    try:
        return create_project(db, **body.model_dump())
    except ProjectError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/{project_id:int}/units:bulk")
def post_bulk_units(
    project_id: int, body: BulkIngestRequest, db: Session = Depends(get_db)
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    rows = parse_jsonl(body.jsonl)
    result = ingest_units(
        db,
        project,
        rows,
        batch_name=body.batch_name,
        source_filename=body.source_filename,
    )
    return ingest_report(result)


@router.get("/{project_id:int}/units", response_model=list[UnitOut])
def get_units(
    project_id: int,
    status: str | None = Query(default=None),
    batch_id: int | None = Query(default=None),
    is_gold: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[Unit]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    stmt = select(Unit).where(Unit.project_id == project_id)
    if status is not None:
        stmt = stmt.where(Unit.status == status)
    if batch_id is not None:
        stmt = stmt.where(Unit.batch_id == batch_id)
    if is_gold is not None:
        stmt = stmt.where(Unit.is_gold == is_gold)
    stmt = stmt.order_by(Unit.priority.desc(), Unit.created_at.asc())
    return list(db.scalars(stmt))
