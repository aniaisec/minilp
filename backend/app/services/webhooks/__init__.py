"""Webhooks (M7, §7.3) — signed, retried, recorded event delivery.

No new trigger logic lives here: events fire off checks that already exist in
§6-§7 (budget caps, rolling gold accuracy, escalation depth, completion). This
package only answers "who is listening, how is it signed, did it arrive".
"""

from app.services.webhooks.dispatch import (
    EVENT_HEADER,
    SIGNATURE_HEADER,
    Sender,
    SendResult,
    emit,
    http_sender,
    set_default_sender,
    sign,
    subscribers,
)

__all__ = [
    "EVENT_HEADER",
    "SIGNATURE_HEADER",
    "SendResult",
    "Sender",
    "emit",
    "http_sender",
    "set_default_sender",
    "sign",
    "subscribers",
]
