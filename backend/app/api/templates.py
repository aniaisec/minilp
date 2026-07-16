"""Template endpoints (§5, §2.5)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_annotator
from app.db import get_db
from app.models import Template, User
from app.schemas.api import (
    PreviewRequest,
    TemplateClone,
    TemplateCreate,
    TemplateOut,
)
from app.services.templates.preview import render_preview
from app.services.templates.repository import (
    TemplateError,
    clone_template,
    create_template,
    edit_template,
    list_templates,
)
from app.services.templates.validation import TemplateValidationError

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateOut])
def get_templates(
    db: Session = Depends(get_db), _user: User = Depends(require_annotator)
) -> list[Template]:
    return list_templates(db)


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
