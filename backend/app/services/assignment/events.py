"""Task-event logging for the assignment engine (measurement instrumentation).

One helper, called at each slot transition the engine performs. It lives beside
the engine rather than in ``slots.lifecycle`` because only the engine knows *why*
a slot is reopening — ``reopen_slot`` is the same call for a skip, an exit, a
judge release and an expiry, and the reason is the whole point of the log.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Slot, TaskEvent, Unit

# What a caller of ``skip_task`` may say about why the lease is going back:
# ``skip`` is the annotator's `s` key, ``exit`` is exit-to-home, ``release`` is a
# judge worker handing back a slot it could not answer (dry run, provider error).
RELEASE_REASONS: dict[str, str] = {"skip": "skipped", "exit": "exited", "release": "released"}


def record_task_event(
    db: Session,
    slot: Slot,
    kind: str,
    *,
    annotator_id: int | None,
    at: datetime | None = None,
    label_id: int | None = None,
) -> TaskEvent:
    """Append one event for ``slot``. Caller flushes."""
    unit = db.get(Unit, slot.unit_id)
    event = TaskEvent(
        project_id=unit.project_id,
        unit_id=slot.unit_id,
        slot_id=slot.id,
        annotator_id=annotator_id,
        label_id=label_id,
        kind=kind,
        at=at or datetime.now(UTC),
    )
    db.add(event)
    return event
