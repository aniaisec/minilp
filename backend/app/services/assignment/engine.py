"""Core assignment logic (M2).

Pure helpers (``should_serve_gold``, ``lease_expiry``) are unit-tested without a
DB; the DB-touching operations are exercised against real PostgreSQL because
``SELECT … FOR UPDATE SKIP LOCKED`` has no SQLite equivalent (§12 execution notes).

State transitions that must be race-safe (leasing a slot, filling a held slot,
releasing a lease) are performed as **atomic conditional statements** in the
database — never as read-then-write on ORM objects. With ``expire_on_commit=False``
a session can hold a stale view of a slot it leased earlier; guarding the write in
SQL (``WHERE status='leased' AND leased_by=:me``) is what prevents a worker whose
lease was reclaimed from writing a second label to the same slot.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Annotator, Label, Project, Slot, Unit


class AssignmentError(Exception):
    """A task operation could not be completed.

    ``status`` mirrors the HTTP code the API layer should surface (404 missing,
    409 conflict such as leasing a slot you don't hold).
    """

    def __init__(self, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _utcnow() -> datetime:
    return datetime.now(UTC)


def lease_expiry(lease_minutes: int, now: datetime | None = None) -> datetime:
    """When a lease taken ``now`` should expire."""
    return (now or _utcnow()) + timedelta(minutes=lease_minutes)


def should_serve_gold(served_total: int, golds_served: int, gold_ratio: float) -> bool:
    """Deficit rule for gold injection (§6.1, §6.4).

    Serve a gold when the annotator's delivered golds have fallen behind the
    target implied by ``gold_ratio`` over everything served so far. Deterministic
    (no RNG) so the injected fraction is testable and reproducible. Golds are
    injected independently of priority — this decides *gold vs real*, the slot
    query then applies priority ordering within that choice.
    """
    if gold_ratio <= 0:
        return False
    if gold_ratio >= 1:
        return True
    target = math.floor((served_total + 1) * gold_ratio)
    return golds_served < target


# --- served/gold accounting -------------------------------------------------


def _served_counts(db: Session, annotator_id: int, project_id: int) -> tuple[int, int]:
    """(total labels, gold labels) this annotator has submitted in the project."""
    base = (
        select(func.count())
        .select_from(Label)
        .join(Unit, Label.unit_id == Unit.id)
        .where(Label.annotator_id == annotator_id, Unit.project_id == project_id)
    )
    served_total = db.scalar(base) or 0
    golds_served = db.scalar(base.where(Unit.is_gold.is_(True))) or 0
    return served_total, golds_served


# --- unit status transitions ------------------------------------------------


def _recompute_unit_status(db: Session, unit_id: int) -> None:
    """Derive a unit's status from its slots (§4 unit lifecycle).

    ``finalized`` is owned by later milestones (merge/review); this engine only
    moves a unit between pending → in_progress → labeled based on slot fill.
    Reads slot statuses as scalar columns (fresh from the DB, not the identity
    map) so it is not fooled by a stale cached Slot object.
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


# --- assignment -------------------------------------------------------------


def _open_slot_query(annotator_id: int, project_id: int, *, is_gold: bool):
    """Best open slot for this annotator, of the given gold-ness, or None.

    Applies annotator-unit exclusion (never the same unit twice, in any variant),
    priority ordering, and ``FOR UPDATE … SKIP LOCKED`` so concurrent workers
    never grab the same row.
    """
    labeled_units = select(Label.unit_id).where(
        Label.annotator_id == annotator_id, Label.is_valid.is_(True)
    )
    leased_units = select(Slot.unit_id).where(
        Slot.leased_by == annotator_id, Slot.status == "leased"
    )
    return (
        select(Slot)
        .join(Unit, Slot.unit_id == Unit.id)
        .where(
            Slot.status == "open",
            Unit.project_id == project_id,
            Unit.is_gold.is_(is_gold),
            Unit.status != "finalized",
            Unit.id.not_in(labeled_units),
            Unit.id.not_in(leased_units),
        )
        .order_by(Unit.priority.desc(), Unit.created_at.asc(), Slot.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True, of=Slot)
    )


def next_task(
    db: Session,
    annotator_id: int,
    project_id: int,
    *,
    now: datetime | None = None,
    sweep: bool = True,
) -> Slot | None:
    """Lease and return the next slot for ``annotator_id`` in ``project_id``.

    Returns ``None`` when no eligible slot remains. Reclaims expired leases first
    (``sweep=True``) so abandoned work re-enters the pool before we look.
    """
    now = now or _utcnow()
    project = db.get(Project, project_id)
    if project is None:
        raise AssignmentError(f"project {project_id} not found", status=404)
    if db.get(Annotator, annotator_id) is None:
        raise AssignmentError(f"annotator {annotator_id} not found", status=404)

    if sweep:
        sweep_expired_leases(db, now=now)

    served_total, golds_served = _served_counts(db, annotator_id, project_id)
    want_gold = should_serve_gold(served_total, golds_served, project.gold_ratio)

    slot: Slot | None = None
    for is_gold in (want_gold, not want_gold):  # fall back to the other pool
        slot = db.scalar(_open_slot_query(annotator_id, project_id, is_gold=is_gold))
        if slot is not None:
            break
    if slot is None:
        return None

    slot.status = "leased"
    slot.leased_by = annotator_id
    slot.lease_expires_at = lease_expiry(project.lease_minutes, now)
    unit = db.get(Unit, slot.unit_id)
    if unit is not None and unit.status == "pending":
        unit.status = "in_progress"
    db.flush()
    return slot


def submit_label(
    db: Session,
    slot_id: int,
    annotator_id: int,
    raw: dict[str, Any],
    value: dict[str, Any] | None = None,
    *,
    confidence: float | None = None,
    reasoning: str | None = None,
    comment: str | None = None,
    latency_ms: int | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_usd: float | None = None,
    cache_hit: bool | None = None,
) -> Label:
    """Record a label for a slot the annotator currently holds (§2.8).

    The fill is an atomic ``UPDATE … WHERE status='leased' AND leased_by=:me``: if
    the lease was reclaimed (expired + swept, then taken by someone else) the
    update matches no row and we refuse — so a stale session can never write a
    second label onto a slot. ``value`` defaults to ``raw`` (equal for
    variant-free templates); canonicalization is layered on in M3/M4.
    """
    slot = db.get(Slot, slot_id, with_for_update=True, populate_existing=True)
    if slot is None:
        raise AssignmentError(f"slot {slot_id} not found", status=404)
    if slot.status != "leased" or slot.leased_by != annotator_id:
        raise AssignmentError("slot is not leased by this annotator", status=409)
    slot.status = "filled"
    slot.lease_expires_at = None
    unit_id = slot.unit_id

    label = Label(
        slot_id=slot_id,
        unit_id=unit_id,
        annotator_id=annotator_id,
        raw=raw,
        value=value if value is not None else raw,
        confidence=confidence,
        reasoning=reasoning,
        comment=comment,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        cache_hit=cache_hit,
        is_valid=True,
    )
    db.add(label)
    db.flush()
    _recompute_unit_status(db, unit_id)
    db.flush()
    return label


def skip_task(db: Session, slot_id: int, annotator_id: int) -> Slot:
    """Release a held lease (``s`` skip): slot reopens, variant retained (§2.7).

    Row-locked so it is race-safe and the session's view of the slot stays
    coherent (same rationale as ``submit_label``).
    """
    slot = db.get(Slot, slot_id, with_for_update=True, populate_existing=True)
    if slot is None:
        raise AssignmentError(f"slot {slot_id} not found", status=404)
    if slot.status != "leased" or slot.leased_by != annotator_id:
        raise AssignmentError("slot is not leased by this annotator", status=409)
    slot.status = "open"
    slot.leased_by = None
    slot.lease_expires_at = None
    db.flush()
    _recompute_unit_status(db, slot.unit_id)
    db.flush()
    return slot


def sweep_expired_leases(db: Session, now: datetime | None = None) -> int:
    """Reclaim leases past ``lease_expires_at``; return how many were reopened.

    Reopened slots keep their variant, so counterbalancing survives abandonment
    (§2.7). Rows are locked with ``SKIP LOCKED`` so concurrent sweepers/workers
    never contend; ``populate_existing`` keeps identity-map state coherent.
    Intended to run periodically (a background sweeper) and opportunistically at
    the head of ``next_task``.
    """
    now = now or _utcnow()
    expired = db.scalars(
        select(Slot)
        .where(Slot.status == "leased", Slot.lease_expires_at < now)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).all()
    for slot in expired:
        slot.status = "open"
        slot.leased_by = None
        slot.lease_expires_at = None
    if expired:
        db.flush()
        for unit_id in {slot.unit_id for slot in expired}:
            _recompute_unit_status(db, unit_id)
        db.flush()
    return len(expired)


def void_unit(db: Session, unit_id: int) -> int:
    """Void a unit's valid labels and reopen its filled slots (§5 PATCH void).

    Invalidated labels stay in the table (audit trail); their slots reopen with
    variant retained so the unit can be re-collected in balance. Returns the
    number of labels voided.
    """
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise AssignmentError(f"unit {unit_id} not found", status=404)
    labels = db.scalars(
        select(Label).where(Label.unit_id == unit_id, Label.is_valid.is_(True))
    ).all()
    for label in labels:
        label.is_valid = False
    slots = db.scalars(
        select(Slot)
        .where(Slot.unit_id == unit_id, Slot.status.in_(("filled", "leased")))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    for slot in slots:
        slot.status = "open"
        slot.leased_by = None
        slot.lease_expires_at = None
    db.flush()
    _recompute_unit_status(db, unit_id)
    db.flush()
    return len(labels)
