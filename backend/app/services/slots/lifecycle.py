"""Slot/unit lifecycle primitives shared by the assignment engine (M2) and the
quality subsystem (M4).

Both need to reopen slots and re-derive unit status: assignment on skip/expiry,
quality when a failing annotator's recent work is voided. They live here so
``services.quality`` and ``services.assignment`` can share them without importing
each other.

Invariant preserved throughout (§2.7): a reopened slot **keeps its variant**, so
counterbalancing survives skips, lease expiry and voids alike.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Label, Slot, Unit


def recompute_unit_status(db: Session, unit_id: int) -> None:
    """Derive a unit's status from its slots (§4 unit lifecycle).

    ``finalized`` is owned by later milestones (merge/review); this only moves a
    unit between pending → in_progress → labeled based on slot fill. Reads slot
    statuses as scalar columns (fresh from the DB, not the identity map) so it is
    not fooled by a stale cached Slot object.
    """
    # Lock the unit row so concurrent last-slot fills serialize: whichever writer
    # acquires the lock second sees the other's committed fill, so the unit is
    # never left in_progress when all its slots are actually filled.
    unit = db.get(Unit, unit_id, with_for_update=True)
    if unit is None or unit.status == "finalized":
        return
    statuses = list(db.scalars(select(Slot.status).where(Slot.unit_id == unit_id)))
    active = [s for s in statuses if s != "voided"]
    if active and all(s == "filled" for s in active):
        unit.status = "labeled"
    elif any(s in ("leased", "filled") for s in statuses):
        unit.status = "in_progress"
    else:
        unit.status = "pending"


def reopen_slot(slot: Slot) -> None:
    """Return a slot to the open pool, retaining its variant (§2.7)."""
    slot.status = "open"
    slot.leased_by = None
    slot.lease_expires_at = None


def void_labels(db: Session, labels: Iterable[Label]) -> int:
    """Invalidate labels and reopen the slots they occupied.

    Labels are kept (``is_valid=False``) as an audit trail — §6.1 requires that a
    paused annotator's history stays inspectable even though it no longer counts.
    Returns the number of labels voided.
    """
    labels = list(labels)
    if not labels:
        return 0

    slot_ids = {label.slot_id for label in labels}
    unit_ids = {label.unit_id for label in labels}

    for label in labels:
        label.is_valid = False

    slots = db.scalars(
        select(Slot)
        .where(Slot.id.in_(slot_ids), Slot.status.in_(("filled", "leased")))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    for slot in slots:
        reopen_slot(slot)

    db.flush()
    for unit_id in unit_ids:
        recompute_unit_status(db, unit_id)
    db.flush()
    return len(labels)
