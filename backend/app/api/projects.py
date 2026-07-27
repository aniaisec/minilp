"""Project + unit-ingest endpoints (§5)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_annotator, require_reviewer
from app.db import get_db
from app.models import Batch, Project, Unit, User
from app.schemas.api import (
    BatchOut,
    BulkIngestRequest,
    ProjectCreate,
    ProjectOut,
    ProjectPatch,
    ProjectSummary,
    ReprioritizeRequest,
    UnitOut,
)
from app.services.analytics import project_roster
from app.services.export import EXPORT_FORMATS, ExportError, iter_jsonl
from app.services.ingest.bulk import FORMATS, ingest_report, ingest_units, parse_payload_text
from app.services.projects import ProjectError, create_project, update_project
from app.services.templates.validation import TemplateValidationError

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
def post_project(
    body: ProjectCreate, db: Session = Depends(get_db), _user: User = Depends(require_admin)
) -> Project:
    try:
        return create_project(db, **body.model_dump())
    except ProjectError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("", response_model=list[ProjectSummary])
def list_projects(
    db: Session = Depends(get_db), _user: User = Depends(require_annotator)
) -> list[Project]:
    """All projects, newest first — the admin project picker / dashboard (§11)."""
    return list(db.scalars(select(Project).order_by(Project.id.desc())))


@router.get("/{project_id:int}", response_model=ProjectOut)
def get_project(
    project_id: int, db: Session = Depends(get_db), _user: User = Depends(require_annotator)
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.patch("/{project_id:int}")
def patch_project(
    project_id: int,
    body: ProjectPatch,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    """Edit a live project's configuration — the third entry point of the one
    editor (§2.5, M6): guidelines, K, agreement policy, gold ratio, thresholds.

    A ``template_schema`` that differs from the bound template **clones and
    rebinds** rather than mutating a version other projects may share; the
    response reports the new template id so the editor can follow it.
    """
    try:
        project, report = update_project(
            db,
            project_id,
            template_schema=body.template_schema,
            labels_per_unit=body.labels_per_unit,
            max_labels_per_unit=body.max_labels_per_unit,
            **body.plain_fields(),
        )
    except TemplateValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors}) from e
    except ProjectError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {
        "project": ProjectOut.model_validate(project).model_dump(),
        **report,
    }


@router.get("/{project_id:int}/export")
def get_export(
    project_id: int,
    format: str = Query(default="labels", description=f"one of {list(EXPORT_FORMATS)}"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_reviewer),
) -> StreamingResponse:
    """Stream a project's labels as JSONL (§10).

    ``labels`` rows re-import through ``units:bulk`` unchanged, so an export is
    also a backup. Reviewer-gated: exports carry per-annotator provenance.
    """
    if format not in EXPORT_FORMATS:
        raise HTTPException(status_code=422, detail=f"format must be one of {list(EXPORT_FORMATS)}")
    try:
        # Materialize eagerly so an ExportError becomes a 422 rather than a
        # truncated 200 with half a file already on the wire.
        lines = list(iter_jsonl(db, project_id, format))
    except ExportError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    filename = f"project-{project_id}-{format}.jsonl"
    return StreamingResponse(
        iter(lines),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{project_id:int}/units:bulk")
def post_bulk_units(
    project_id: int,
    body: BulkIngestRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if body.format not in FORMATS:
        raise HTTPException(status_code=422, detail=f"format must be one of {list(FORMATS)}")
    rows = parse_payload_text(body.jsonl, body.format)
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
    escalated: bool | None = Query(
        default=None, description="Filter to units routed for review (or not)."
    ),
    min_priority: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_annotator),
) -> list[Unit]:
    """Browse/filter units — the M5 unit browser. Filters compose (§11)."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    stmt = select(Unit).where(Unit.project_id == project_id)
    if status is not None:
        stmt = stmt.where(Unit.status == status)
    if batch_id is not None:
        stmt = stmt.where(Unit.batch_id == batch_id)
    if is_gold is not None:
        stmt = stmt.where(Unit.is_gold == is_gold)
    if escalated is True:
        stmt = stmt.where(Unit.escalated_at.is_not(None))
    elif escalated is False:
        stmt = stmt.where(Unit.escalated_at.is_(None))
    if min_priority is not None:
        stmt = stmt.where(Unit.priority >= min_priority)
    stmt = stmt.order_by(Unit.priority.desc(), Unit.created_at.asc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


@router.get("/{project_id:int}/batches", response_model=list[BatchOut])
def get_batches(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_annotator),
) -> list[Batch]:
    """Batches for the project — populates the unit-browser batch filter (§11)."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return list(db.scalars(select(Batch).where(Batch.project_id == project_id).order_by(Batch.id)))


@router.get("/{project_id:int}/annotators")
def get_annotators(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_reviewer),
) -> dict:
    """Annotator roster with reputation and gold accuracy (§11 dashboard)."""
    try:
        return project_roster(db, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{project_id:int}/units:reprioritize")
def post_reprioritize(
    project_id: int,
    body: ReprioritizeRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    """Bulk priority update by batch or status (§5, §6.4 prioritization)."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    stmt = select(Unit).where(Unit.project_id == project_id)
    if body.batch_id is not None:
        stmt = stmt.where(Unit.batch_id == body.batch_id)
    if body.status is not None:
        stmt = stmt.where(Unit.status == body.status)
    units = list(db.scalars(stmt))
    for unit in units:
        unit.priority = body.priority
    db.flush()
    return {"project_id": project_id, "updated": len(units), "priority": body.priority}
