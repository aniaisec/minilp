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
from app.services.quality.pipeline import QualityOutcome, on_label_submitted
from app.services.quality.reputation import compute_reputation
from app.services.slots.lifecycle import recompute_unit_status, reopen_slot, void_labels


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

# ``recompute_unit_status`` moved to ``services.slots.lifecycle`` in M4 so the
# quality subsystem can void labels without importing the assignment engine.
# Re-exported under the old private name for callers inside this package.
_recompute_unit_status = recompute_unit_status


# --- eligibility gating (§6.2) ----------------------------------------------


def check_eligibility(db: Session, annotator: Annotator, project: Project) -> None:
    """Refuse work to a paused or below-threshold annotator (§6.1, §6.2).

    Raised rather than returning ``None`` so the caller can tell "you are paused"
    apart from "the queue is empty" — the annotation UI shows a very different
    screen for each, and silently handing an annotator an empty queue when they
    have actually been suspended is the kind of thing that wastes an afternoon.

    When the project gates on reputation the score is recomputed live rather than
    read from the cached column: the cache is only written after a label lands, so
    a never-scored annotator would sit at the column default of 0.0 and be locked
    out of a ``min_reputation`` project before submitting anything. The live
    computation applies the §6.2 prior, which starts them near 1.0.
    """
    if annotator.status != "active":
        reason = annotator.pause_reason or f"annotator is {annotator.status}"
        raise AssignmentError(reason, status=403)
    if project.min_reputation <= 0:
        return
    score = compute_reputation(db, annotator.id, project_id=project.id).score
    if score < project.min_reputation:
        raise AssignmentError(
            f"reputation {score:.2f} is below the project minimum {project.min_reputation:.2f}",
            status=403,
        )


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


def _eligible_open_units_subquery(annotator_id: int):
    """Units this annotator could still be served an open slot on.

    Same exclusion the assignment query applies (§2.7): never a unit they already
    labeled, never one they currently hold a lease on, never a finalized unit."""
    labeled_units = select(Label.unit_id).where(
        Label.annotator_id == annotator_id, Label.is_valid.is_(True)
    )
    leased_units = select(Slot.unit_id).where(
        Slot.leased_by == annotator_id, Slot.status == "leased"
    )
    return labeled_units, leased_units


def available_work(db: Session, annotator_id: int, *, now: datetime | None = None) -> list[dict]:
    """Per-project count of open slots this annotator is still eligible for.

    Powers the annotator landing page (M5): the number returned for a project is
    exactly what ``next_task`` would keep serving — same annotator-unit exclusion,
    same finalized-unit filter — counting gold and non-gold slots together so a
    landing total never leaks which units are golds (§6.1). Projects the annotator
    is blocked from (paused, or below ``min_reputation``) report their remaining
    work but carry an ``eligible: false`` / ``blocked_reason`` so the UI can show
    *why* rather than a mysterious empty row.

    Ordered with the most work first, and projects that still need labels ahead of
    those that don't — the landing page's default sort.
    """
    now = now or _utcnow()
    annotator = db.get(Annotator, annotator_id)
    if annotator is None:
        raise AssignmentError(f"annotator {annotator_id} not found", status=404)

    # Reclaim abandoned leases first so counts reflect currently-available work.
    sweep_expired_leases(db, now=now)

    labeled_units, leased_units = _eligible_open_units_subquery(annotator_id)

    # Eligible open slots per project, and the distinct units behind them.
    rows = db.execute(
        select(
            Unit.project_id,
            func.count(Slot.id),
            func.count(func.distinct(Slot.unit_id)),
        )
        .select_from(Slot)
        .join(Unit, Slot.unit_id == Unit.id)
        .where(
            Slot.status == "open",
            Unit.status != "finalized",
            Unit.id.not_in(labeled_units),
            Unit.id.not_in(leased_units),
        )
        .group_by(Unit.project_id)
    ).all()
    open_by_project = {pid: (slots, units) for pid, slots, units in rows}

    # Labels this annotator has already contributed, per project.
    served_rows = db.execute(
        select(Unit.project_id, func.count())
        .select_from(Label)
        .join(Unit, Label.unit_id == Unit.id)
        .where(Label.annotator_id == annotator_id, Label.is_valid.is_(True))
        .group_by(Unit.project_id)
    ).all()
    served_by_project = {pid: n for pid, n in served_rows}

    out = []
    for project in db.scalars(select(Project).order_by(Project.id)):
        available, open_units = open_by_project.get(project.id, (0, 0))
        eligible, blocked = True, None
        try:
            check_eligibility(db, annotator, project)
        except AssignmentError as e:
            eligible, blocked = False, str(e)
        out.append(
            {
                "project_id": project.id,
                "name": project.name,
                "description": project.description,
                "template_id": project.template_id,
                "template_version": project.template_version,
                "labels_per_unit": project.labels_per_unit,
                "available_labels": available,
                "open_units": open_units,
                "your_labels": served_by_project.get(project.id, 0),
                "eligible": eligible,
                "blocked_reason": blocked,
            }
        )
    # Most work first; projects still needing labels ahead of finished ones.
    out.sort(key=lambda r: (r["available_labels"] > 0, r["available_labels"]), reverse=True)
    return out


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
    annotator = db.get(Annotator, annotator_id)
    if annotator is None:
        raise AssignmentError(f"annotator {annotator_id} not found", status=404)
    check_eligibility(db, annotator, project)

    if sweep:
        sweep_expired_leases(db, now=now)

    # Resume an existing hold before handing out anything new. Pull-based
    # assignment leases a slot the instant the annotation view loads, so a
    # reload / revisit would otherwise strand that in-progress task: the
    # annotator-unit exclusion (§2.7) hides a unit they already hold from
    # themselves, leaving "all caught up" while the slot sits leased until it
    # expires. Returning the held slot (and refreshing its lease) makes a reload
    # pick up exactly where they left off, and keeps one annotator to one open
    # task at a time.
    held = db.scalar(
        select(Slot)
        .join(Unit, Slot.unit_id == Unit.id)
        .where(
            Slot.status == "leased",
            Slot.leased_by == annotator_id,
            Unit.project_id == project_id,
        )
        .order_by(Slot.lease_expires_at.asc().nulls_first(), Slot.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True, of=Slot)
    )
    if held is not None:
        held.lease_expires_at = lease_expiry(project.lease_minutes, now)
        db.flush()
        return held

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
    run_quality: bool = True,
) -> Label:
    """Record a label for a slot the annotator currently holds (§2.8).

    The fill is an atomic ``UPDATE … WHERE status='leased' AND leased_by=:me``: if
    the lease was reclaimed (expired + swept, then taken by someone else) the
    update matches no row and we refuse — so a stale session can never write a
    second label onto a slot.

    ``value`` from the client is advisory: since M4 the quality pipeline
    recanonicalizes server-side from ``raw`` + the slot's variant (§2.6), then
    grades golds, updates reputation and evaluates consensus. The resulting
    ``QualityOutcome`` is attached to the returned label as ``label.quality`` for
    the API layer; it is deliberately *not* persisted on the label row, because
    nothing in it belongs to the label itself. ``run_quality=False`` is for
    fixtures that want a bare insert.
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
    recompute_unit_status(db, unit_id)
    db.flush()

    outcome = on_label_submitted(db, label) if run_quality else QualityOutcome()
    label.quality = outcome  # transient attribute, read by the API layer
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
    reopen_slot(slot)
    db.flush()
    recompute_unit_status(db, slot.unit_id)
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
        reopen_slot(slot)
    if expired:
        db.flush()
        for unit_id in {slot.unit_id for slot in expired}:
            recompute_unit_status(db, unit_id)
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
    # Also reopen slots that hold no label (leased-but-unsubmitted), which
    # ``void_labels`` would not see.
    voided = void_labels(db, labels)
    stranded = db.scalars(
        select(Slot)
        .where(Slot.unit_id == unit_id, Slot.status.in_(("filled", "leased")))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    for slot in stranded:
        reopen_slot(slot)
    db.flush()
    recompute_unit_status(db, unit_id)
    db.flush()
    return voided
