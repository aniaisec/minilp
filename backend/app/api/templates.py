"""Template endpoints (§5, §2.5)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_annotator
from app.db import get_db
from app.models import Template, User
from app.schemas.api import (
    PreviewRequest,
    SampleUpdate,
    TemplateClone,
    TemplateCreate,
    TemplateOut,
)
from app.services.marketplace import export_template_bundle
from app.services.templates.preview import render_preview
from app.services.templates.repository import (
    TemplateError,
    TemplateInUseError,
    clone_template,
    create_template,
    delete_template,
    edit_template,
    list_templates,
    template_usage,
)
from app.services.templates.sample import SampleError, get_sample, save_sample
from app.services.templates.validation import TemplateValidationError

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateOut])
def get_templates(
    db: Session = Depends(get_db), _user: User = Depends(require_annotator)
) -> list[Template]:
    return list_templates(db)


@router.get("/{template_id:int}", response_model=TemplateOut)
def get_template(
    template_id: int, db: Session = Depends(get_db), _user: User = Depends(require_annotator)
) -> Template:
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
    return template


@router.post("", response_model=TemplateOut, status_code=201)
def post_template(
    body: TemplateCreate, db: Session = Depends(get_db), _user: User = Depends(require_admin)
) -> Template:
    try:
        return create_template(db, body.schema_)
    except TemplateValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors}) from e


@router.post("/{template_id:int}:clone", response_model=TemplateOut, status_code=201)
def post_clone(
    template_id: int,
    body: TemplateClone | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> Template:
    try:
        return clone_template(db, template_id, new_name=(body.new_name if body else None))
    except TemplateError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/{template_id:int}", response_model=TemplateOut)
def put_template(
    template_id: int,
    body: TemplateCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> Template:
    try:
        return edit_template(db, template_id, body.schema_)
    except TemplateValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors}) from e
    except TemplateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.delete("/{template_id:int}")
def delete_template_endpoint(
    template_id: int,
    versions: str = Query(
        default="one",
        description="'one' deletes just this version; 'all' deletes every version "
        "sharing the name (all-or-nothing).",
    ),
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    """Delete a custom template version, or its whole lineage (§2.5).

    Refuses builtins (clone instead) and any version a project is bound to — the
    409 body carries ``blockers`` so the caller gets the project names rather
    than a foreign-key error. Deleting is admin-only for the same reason creating
    is: a template is the definition of every label collected under it.
    """
    if versions not in ("one", "all"):
        raise HTTPException(status_code=422, detail="versions must be 'one' or 'all'")
    try:
        return delete_template(db, template_id, all_versions=versions == "all")
    except TemplateInUseError as e:
        raise HTTPException(
            status_code=409, detail={"message": str(e), "blockers": e.blockers}
        ) from e
    except TemplateError as e:
        # "not found" is a 404; "builtin" is a refusal to act on a real row.
        status = 404 if "not found" in str(e) else 409
        raise HTTPException(status_code=status, detail=str(e)) from e


@router.get("/{template_id:int}/usage")
def get_template_usage(
    template_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_annotator),
) -> dict:
    """Which projects are bound to this template version.

    The gallery reads it to explain *before* you click delete why the button is
    disabled, rather than after."""
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
    lineage = list(db.scalars(select(Template.id).where(Template.name == template.name)))
    return {
        "template_id": template_id,
        "kind": template.kind,
        "deletable": template.kind != "builtin" and not template_usage(db, [template_id]),
        "projects": template_usage(db, [template_id]),
        "lineage_projects": template_usage(db, lineage),
        "versions": len(lineage),
    }


@router.get("/{template_id:int}/sample")
def get_template_sample(
    template_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_annotator),
) -> dict:
    """The template's saved example payload (or a generated one) + field breakdown.

    Powers the gallery preview and the wizard's format example (§11)."""
    tmpl = db.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    return get_sample(db, tmpl)


@router.put("/{template_id:int}/sample")
def put_template_sample(
    template_id: int,
    body: SampleUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    """Save an edited example payload (admin). Rejected if it misses a required
    field; saving never bumps the schema version (§2.5 — this is metadata)."""
    tmpl = db.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    try:
        return save_sample(db, tmpl, body.sample)
    except SampleError as e:
        raise HTTPException(status_code=422, detail={"errors": e.problems}) from e


@router.get("/{template_id:int}:export")
def get_template_export(
    template_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    """A template as a shareable JSON bundle (§12, M10) — import it on a fresh
    instance via ``POST /marketplace/import`` and it validates and previews
    identically, the same guarantee a gallery template gets at boot."""
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
    return export_template_bundle(template)


@router.post("/{template_id:int}/preview")
def post_preview(
    template_id: int,
    body: PreviewRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_annotator),
) -> dict:
    tmpl = db.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    return render_preview(tmpl.schema, body.payload)
