"""Webhook dispatch (§7.3) — HMAC-signed, retried, and *always* recorded.

§7.3's claim is that webhooks add no new trigger logic: every event fires off a
check that already exists in §6-§7. This module is therefore only three things —
who is subscribed, how the payload is signed, and what happened when we sent it.

Two decisions worth stating:

**Emission never raises.** A judge run that completed its work must not be
reported as failed because a listener's endpoint is down. Every failure path ends
in a persisted ``WebhookDelivery`` row with ``status='failed'`` and the error
text, which is strictly more useful than an exception nobody is positioned to
handle. This is the "fire-and-forget with retry" of §7.3, made auditable.

**The sender is injectable.** ``Sender`` is a one-method protocol; the default
posts with httpx, and tests pass a recorder. That is what lets "budget cap
hard-stops and fires its webhook" be a real assertion about the event, the
payload and the signature rather than a mock-patching exercise.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Webhook, WebhookDelivery
from app.models.webhook import WEBHOOK_EVENTS

SIGNATURE_HEADER = "X-MiniLP-Signature"
EVENT_HEADER = "X-MiniLP-Event"


@dataclass(frozen=True)
class SendResult:
    ok: bool
    status_code: int | None = None
    error: str | None = None


class Sender(Protocol):
    def __call__(self, url: str, body: str, headers: dict[str, str]) -> SendResult: ...


def sign(secret: str | None, body: str) -> str | None:
    """HMAC-SHA256 of the exact bytes sent, hex-encoded (``sha256=<hex>``).

    Signing the serialized body rather than a re-serialization of the payload is
    the whole point: a receiver that re-encodes the JSON to verify would get a
    different byte string and a failed check.
    """
    if not secret:
        return None
    digest = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def http_sender(timeout: float = 10.0) -> Sender:
    """The production sender — one POST, no follow-up."""

    def _send(url: str, body: str, headers: dict[str, str]) -> SendResult:
        try:
            import httpx
        except ImportError as e:  # pragma: no cover - environment-dependent
            return SendResult(False, error=f"httpx unavailable: {e}")
        try:
            response = httpx.post(
                url,
                content=body.encode("utf-8"),
                headers={**headers, "content-type": "application/json"},
                timeout=timeout,
            )
        except Exception as e:
            return SendResult(False, error=str(e)[:500])
        return SendResult(
            ok=response.status_code < 400,
            status_code=response.status_code,
            error=None if response.status_code < 400 else response.text[:500],
        )

    return _send


_default_sender: Sender | None = None


def set_default_sender(sender: Sender | None) -> None:
    """Override the process-wide sender (used by the demo and by tests)."""
    global _default_sender
    _default_sender = sender


def subscribers(db: Session, event: str, project_id: int | None) -> list[Webhook]:
    """Active webhooks for an event: this project's, plus instance-wide ones (§4)."""
    stmt = select(Webhook).where(Webhook.event == event, Webhook.status == "active")
    hooks = list(db.scalars(stmt))
    return [h for h in hooks if h.project_id is None or h.project_id == project_id]


def emit(
    db: Session,
    event: str,
    *,
    project_id: int | None = None,
    payload: dict[str, Any] | None = None,
    sender: Sender | None = None,
    attempts: int = 3,
    backoff: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> list[WebhookDelivery]:
    """Deliver ``event`` to every subscriber; return the delivery records.

    Returns an empty list when nobody is listening — emitting into the void is
    free and callers never need to check first.
    """
    if event not in WEBHOOK_EVENTS:
        raise ValueError(f"unknown webhook event '{event}' (known: {list(WEBHOOK_EVENTS)})")
    hooks = subscribers(db, event, project_id)
    if not hooks:
        return []

    send = sender or _default_sender or http_sender()
    body_obj = {
        "event": event,
        "project_id": project_id,
        "sent_at": time.time(),
        **(payload or {}),
    }
    body = json.dumps(body_obj, sort_keys=True, default=str)

    deliveries: list[WebhookDelivery] = []
    for hook in hooks:
        signature = sign(hook.secret, body)
        headers = {EVENT_HEADER: event}
        if signature:
            headers[SIGNATURE_HEADER] = signature
        delivery = WebhookDelivery(
            webhook_id=hook.id,
            event=event,
            project_id=project_id,
            payload=body_obj,
            status="pending",
            signature=signature,
        )
        db.add(delivery)

        result = SendResult(False, error="not attempted")
        for attempt in range(1, max(1, attempts) + 1):
            delivery.attempts = attempt
            try:
                result = send(hook.target_url, body, headers)
            except Exception as e:  # a sender must never break the caller
                result = SendResult(False, error=f"sender raised: {e}"[:500])
            if result.ok:
                break
            if attempt < attempts:
                sleep(backoff * (2 ** (attempt - 1)))
        delivery.status = "delivered" if result.ok else "failed"
        delivery.status_code = result.status_code
        delivery.error = result.error
        deliveries.append(delivery)

    db.flush()
    return deliveries
