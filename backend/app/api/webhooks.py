"""Webhook registration + delivery log (§5, §7.3).

Admin-gated: a webhook is an outbound channel carrying project metrics, so
registering one is the same class of decision as creating a judge.

The secret is write-only. ``WebhookOut`` reports ``has_secret`` and never the
value — a listing endpoint that echoes signing keys turns any read-access leak
into a forgery capability.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_reviewer
from app.db import get_db
from app.models import Project, User, Webhook, WebhookDelivery
from app.models.webhook import WEBHOOK_EVENTS
from app.schemas.api import WebhookCreate, WebhookDeliveryOut, WebhookOut

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _out(hook: Webhook) -> WebhookOut:
    return WebhookOut(
        id=hook.id,
        event=hook.event,
        target_url=hook.target_url,
        project_id=hook.project_id,
        status=hook.status,
        has_secret=bool(hook.secret),
    )


@router.get("/events")
def get_events(_user: User = Depends(require_reviewer)) -> dict:
    """The event names a webhook may subscribe to (§7.3)."""
    return {"events": list(WEBHOOK_EVENTS)}


@router.post("", response_model=WebhookOut, status_code=201)
def post_webhook(
    body: WebhookCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> WebhookOut:
    if body.event not in WEBHOOK_EVENTS:
        raise HTTPException(status_code=422, detail=f"event must be one of {list(WEBHOOK_EVENTS)}")
    if body.project_id is not None and db.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not body.target_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="target_url must be http(s)")
    hook = Webhook(
        event=body.event,
        target_url=body.target_url,
        secret=body.secret,
        project_id=body.project_id,
        status="active",
    )
    db.add(hook)
    db.flush()
    return _out(hook)


@router.get("", response_model=list[WebhookOut])
def get_webhooks(
    project: int | None = Query(default=None, description="Filter to one project's hooks."),
    db: Session = Depends(get_db),
    _user: User = Depends(require_reviewer),
) -> list[WebhookOut]:
    stmt = select(Webhook).order_by(Webhook.id)
    if project is not None:
        stmt = stmt.where(Webhook.project_id == project)
    return [_out(h) for h in db.scalars(stmt)]


@router.delete("/{webhook_id:int}", status_code=200)
def delete_webhook(
    webhook_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict:
    hook = db.get(Webhook, webhook_id)
    if hook is None:
        raise HTTPException(status_code=404, detail="webhook not found")
    db.delete(hook)
    db.flush()
    return {"deleted": webhook_id}


@router.get("/deliveries", response_model=list[WebhookDeliveryOut])
def get_deliveries(
    webhook: int | None = Query(default=None),
    project: int | None = Query(default=None),
    event: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(require_reviewer),
) -> list[WebhookDelivery]:
    """Delivery log — what fired, whether it arrived, and after how many tries."""
    stmt = select(WebhookDelivery).order_by(WebhookDelivery.id.desc()).limit(limit)
    if webhook is not None:
        stmt = stmt.where(WebhookDelivery.webhook_id == webhook)
    if project is not None:
        stmt = stmt.where(WebhookDelivery.project_id == project)
    if event is not None:
        stmt = stmt.where(WebhookDelivery.event == event)
    return list(db.scalars(stmt))
