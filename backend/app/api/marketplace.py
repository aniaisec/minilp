"""Marketplace endpoints (§5, §12, M10) — browse the local shared-bundle
directory and import a bundle (shipped or pasted).

Admin-gated throughout, the same bucket as templates and judges: importing a
bundle creates templates, judge configs, and possibly a project, which is the
same "decision to author" §5 already gates admin-only.

Export endpoints for a single template / judge config / project live on their
own routers (``GET /templates/{id}:export``, ``GET /judges/{id}:export``,
``GET /projects/{id}:export-bundle``) rather than here, so a bundle for a thing
sits next to the thing's other endpoints — the same layout choice §5 already
makes for preview and usage.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db import get_db
from app.models import User
from app.schemas.api import MarketplaceImportRequest
from app.services.judges.configs import JudgeError
from app.services.marketplace import (
    LocalBundleError,
    MarketplaceError,
    import_bundle,
    list_local_bundles,
    read_local_bundle,
)
from app.services.projects.service import ProjectError
from app.services.templates.validation import TemplateValidationError

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


def _serialize(result: dict) -> dict:
    """ORM objects -> plain ids/names for a JSON response; a bundle import
    returns a summary, not the full ``TemplateOut``/``JudgeConfigOut`` shape."""
    out: dict = {"kind": result["kind"]}
    if "template" in result:
        t = result["template"]
        out["template"] = {"id": t.id, "name": t.name, "version": t.version}
    if "judge_config" in result:
        c = result["judge_config"]
        out["judge_config"] = {"id": c.id, "name": c.name, "prompt_version": c.prompt_version}
    if "judge_configs" in result:
        out["judge_configs"] = [
            {"id": c.id, "name": c.name, "prompt_version": c.prompt_version}
            for c in result["judge_configs"]
        ]
    if "project" in result:
        p = result["project"]
        out["project"] = {"id": p.id, "name": p.name}
    return out


def _import_error(e: Exception) -> HTTPException:
    if isinstance(e, TemplateValidationError):
        return HTTPException(status_code=422, detail={"errors": e.errors})
    if isinstance(e, JudgeError):
        return HTTPException(status_code=e.status, detail=str(e))
    if isinstance(e, ProjectError | MarketplaceError):
        return HTTPException(status_code=422, detail=str(e))
    raise e


@router.get("/bundles")
def get_local_bundles(_user: User = Depends(require_admin)) -> dict:
    """Metadata for every bundle shipped in the repo's local directory (§12: "a
    local directory of shared bundles ships with the repo — no hosted registry
    in v1")."""
    return {"bundles": list_local_bundles()}


@router.get("/bundles/{filename}")
def get_local_bundle(filename: str, _user: User = Depends(require_admin)) -> dict:
    """The full bundle document for one shipped file — for inspecting before
    importing it."""
    try:
        return read_local_bundle(filename)
    except LocalBundleError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/bundles/{filename}:import", status_code=201)
def post_import_local_bundle(
    filename: str,
    create_project: bool = True,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    """Import one of the shipped bundles by filename — one click, no copy/paste."""
    try:
        bundle = read_local_bundle(filename)
    except LocalBundleError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        result = import_bundle(db, bundle, create_project_row=create_project)
    except (TemplateValidationError, JudgeError, ProjectError, MarketplaceError) as e:
        raise _import_error(e) from e
    return _serialize(result)


@router.post("/import", status_code=201)
def post_import(
    body: MarketplaceImportRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    """Import a pasted or uploaded bundle. Reuses the exact validation path
    ``POST /templates`` / ``POST /judges`` / ``POST /projects`` already run — an
    imported bundle gets no special trust (§2.1, M1 acceptance)."""
    try:
        result = import_bundle(db, body.bundle, create_project_row=body.create_project)
    except (TemplateValidationError, JudgeError, ProjectError, MarketplaceError) as e:
        raise _import_error(e) from e
    return _serialize(result)
