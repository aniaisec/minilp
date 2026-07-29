"""Judge endpoints (§5, §7.1) — configs, enrollment, runs.

Admin-gated throughout: §5 puts judges in the same bucket as templates, projects
and webhooks, because creating one is a decision to spend money.

Note what is *not* here. There is no judge-specific "submit" endpoint and no
judge queue: a judge takes work through ``/tasks/next`` and writes it through
``/tasks/{slot}/submit`` like anyone else. This router only decides *which* judge
runs *where*, and for how long.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_reviewer
from app.db import get_db
from app.models import JudgeConfig, JudgeRun, Project, User
from app.schemas.api import (
    JudgeConfigCreate,
    JudgeConfigOut,
    JudgeConfigVersion,
    JudgeRunOut,
    JudgeRunRequest,
)
from app.services.judges import (
    JudgeError,
    attach_judge,
    create_judge_config,
    detach_judge,
    enrolled_judges,
    judge_display_name,
    judge_spend,
    list_judge_configs,
    new_version,
    provider_names,
    resolve_enrollment,
    resolve_price,
    run_judge,
)

router = APIRouter(tags=["judges"])


def _judge_error(e: JudgeError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=str(e))


@router.get("/judges/providers")
def get_providers(_user: User = Depends(require_admin)) -> dict:
    """Provider names the orchestrator can build — populates the config form."""
    return {"providers": provider_names()}


@router.post("/judges", response_model=JudgeConfigOut, status_code=201)
def post_judge(
    body: JudgeConfigCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> JudgeConfig:
    try:
        return create_judge_config(db, **body.model_dump())
    except JudgeError as e:
        raise _judge_error(e) from e


@router.get("/judges", response_model=list[JudgeConfigOut])
def get_judges(
    name: str | None = Query(default=None, description="Filter to one config's versions."),
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> list[JudgeConfig]:
    return list_judge_configs(db, name=name)


@router.get("/judges/{judge_config_id:int}", response_model=JudgeConfigOut)
def get_judge(
    judge_config_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> JudgeConfig:
    config = db.get(JudgeConfig, judge_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="judge config not found")
    return config


@router.post(
    "/judges/{judge_config_id:int}:version",
    response_model=JudgeConfigOut,
    status_code=201,
)
def post_judge_version(
    judge_config_id: int,
    body: JudgeConfigVersion,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> JudgeConfig:
    """Write the next prompt version (§4: immutable per version, edits bump).

    The old version keeps its annotator and its labels, so a project mid-run does
    not silently switch judges under you — attach the new version explicitly.
    """
    try:
        return new_version(db, judge_config_id, **body.changes())
    except JudgeError as e:
        raise _judge_error(e) from e


@router.post("/projects/{project_id:int}/judges/{judge_config_id:int}:attach")
def post_attach(
    project_id: int,
    judge_config_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    """Enroll a judge on a project as a ``kind=model`` annotator (§7.1)."""
    try:
        return attach_judge(db, project_id, judge_config_id)
    except JudgeError as e:
        raise _judge_error(e) from e


@router.post("/projects/{project_id:int}/judges/{judge_config_id:int}:detach")
def post_detach(
    project_id: int,
    judge_config_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    """Stop giving a judge work. Its existing labels stay valid."""
    try:
        return detach_judge(db, project_id, judge_config_id)
    except JudgeError as e:
        raise _judge_error(e) from e


@router.get("/projects/{project_id:int}/judges")
def get_project_judges(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_reviewer),
) -> dict:
    """Judges enrolled on this project, with live spend against their caps."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    out = []
    for entry in enrolled_judges(project):
        config = db.get(JudgeConfig, entry["judge_config_id"])
        if config is None:
            continue
        annotator_id = entry.get("annotator_id")
        spend = judge_spend(db, project_id, annotator_id) if annotator_id else None
        price = resolve_price(config.model_id, config.params, provider=config.provider)
        out.append(
            {
                "judge_config_id": config.id,
                "annotator_id": annotator_id,
                "display_name": judge_display_name(config),
                "provider": config.provider,
                "model_id": config.model_id,
                "prompt_version": config.prompt_version,
                "budget": config.budget,
                "priced": price.priced,
                "price_source": price.source,
                "spend": {
                    "cost_usd": spend.cost_usd,
                    "daily_usd": spend.daily_usd,
                    "tokens": spend.tokens,
                    "labels": spend.labels,
                    "cache_hits": spend.cache_hits,
                }
                if spend
                else None,
            }
        )
    return {"project_id": project_id, "judges": out}


@router.post("/projects/{project_id:int}/judges:run")
def post_run(
    project_id: int,
    body: JudgeRunRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    """Run one or every enrolled judge over the project's open slots (§7.1).

    Synchronous by design at this size: a bounded run (default 100 slots) returns
    a report the admin can act on, and a background queue would add a whole
    operational surface — workers, retries, status polling — for a feature whose
    guardrails are already "stop at the cap". ``dry_run`` prices the same work
    without calling the provider.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    if body.judge_config_id is not None:
        targets = [body.judge_config_id]
    else:
        targets = [e["judge_config_id"] for e in enrolled_judges(project)]
    if not targets:
        raise HTTPException(
            status_code=409, detail="no judges enrolled on this project; attach one first"
        )

    runs = []
    for judge_config_id in targets:
        try:
            result = run_judge(
                db,
                project_id,
                judge_config_id,
                limit=body.limit,
                dry_run=body.dry_run,
            )
        except JudgeError as e:
            raise _judge_error(e) from e
        runs.append(result.as_dict())
    return {
        "project_id": project_id,
        "dry_run": body.dry_run,
        "runs": runs,
        "labels_written": sum(r["labels_written"] for r in runs),
        "cost_usd": round(sum(r["cost_usd"] for r in runs), 6),
        "estimated_cost_usd": round(sum(r["estimated_cost_usd"] or 0.0 for r in runs), 6)
        if body.dry_run
        else None,
    }


@router.get("/projects/{project_id:int}/judge-runs", response_model=list[JudgeRunOut])
def get_runs(
    project_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(require_reviewer),
) -> list[JudgeRun]:
    """Run history — dry runs and live runs side by side (§7.1)."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return list(
        db.scalars(
            select(JudgeRun)
            .where(JudgeRun.project_id == project_id)
            .order_by(JudgeRun.id.desc())
            .limit(limit)
        )
    )


@router.get("/projects/{project_id:int}/judges/{judge_config_id:int}/enrollment")
def get_enrollment(
    project_id: int,
    judge_config_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_reviewer),
) -> dict:
    """Resolve which annotator a judge acts as here — used by the UI and by curl."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        annotator = resolve_enrollment(db, project, judge_config_id)
    except JudgeError as e:
        raise _judge_error(e) from e
    return {
        "project_id": project_id,
        "judge_config_id": judge_config_id,
        "annotator_id": annotator.id,
        "display_name": annotator.display_name,
        "status": annotator.status,
        "reputation_score": annotator.reputation_score,
    }
