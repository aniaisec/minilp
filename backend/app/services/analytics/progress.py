"""Project progress: funnel, per-batch and per-variant fill, per-key consensus
rates, throughput and ETA (§5 ``/progress``, §11 progress view).

The numbers here are the ones the acceptance test reconciles against raw DB state,
so every figure is derived from a single authoritative query rather than a cached
snapshot — except per-key consensus, which reads each unit's cached ``quality``
block (written by the M4 consensus evaluator) and recomputes on the fly for units
labeled before that cache existed.

Throughput/ETA are factored into a pure helper (``throughput``) so the rate
formula can be pinned by a fixture without standing up a clock.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Batch, Label, Project, Slot, Unit
from app.services.quality.consensus import evaluate_unit
from app.services.slots.generation import variant_values

# Default trailing window over which "current rate" is measured.
DEFAULT_THROUGHPUT_WINDOW_HOURS = 24.0


@dataclass(frozen=True)
class Throughput:
    """Labels/hour over a trailing window and the ETA it implies."""

    labels_per_hour: float
    window_hours: float
    labels_in_window: int
    remaining_slots: int
    eta_hours: float | None  # None when the rate is zero (ETA undefined)

    def as_dict(self) -> dict[str, Any]:
        return {
            "labels_per_hour": round(self.labels_per_hour, 4),
            "window_hours": self.window_hours,
            "labels_in_window": self.labels_in_window,
            "remaining_slots": self.remaining_slots,
            "eta_hours": round(self.eta_hours, 4) if self.eta_hours is not None else None,
        }


def throughput(
    submitted_at: list[datetime],
    remaining_slots: int,
    *,
    now: datetime,
    window_hours: float = DEFAULT_THROUGHPUT_WINDOW_HOURS,
) -> Throughput:
    """Current labelling rate and ETA — pure, so a fixture can pin the formula.

    ``rate = (labels submitted within the trailing window) / window_hours``;
    ``eta_hours = remaining_slots / rate`` (``None`` when rate is 0). Using a fixed
    window rather than "since first label" keeps the rate responsive to a stalled
    project instead of averaging in a burst from days ago.
    """
    cutoff = now - timedelta(hours=window_hours)
    in_window = sum(1 for t in submitted_at if _aware(t) >= cutoff)
    rate = in_window / window_hours if window_hours > 0 else 0.0
    eta = (remaining_slots / rate) if rate > 0 else None
    return Throughput(rate, window_hours, in_window, remaining_slots, eta)


def _aware(dt: datetime) -> datetime:
    """Treat a naive timestamp as UTC (Postgres may hand back either)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _funnel(db: Session, project_id: int) -> dict[str, int]:
    rows = db.execute(
        select(Unit.status, func.count()).where(Unit.project_id == project_id).group_by(Unit.status)
    ).all()
    funnel = {"pending": 0, "in_progress": 0, "labeled": 0, "finalized": 0}
    for status, count in rows:
        funnel[status] = count
    funnel["total"] = sum(v for k, v in funnel.items() if k != "total")
    escalated = db.scalar(
        select(func.count())
        .select_from(Unit)
        .where(Unit.project_id == project_id, Unit.escalated_at.is_not(None))
    )
    funnel["escalated"] = escalated or 0
    return funnel


def _slot_status_counts(db: Session, project_id: int) -> dict[str, int]:
    rows = db.execute(
        select(Slot.status, func.count())
        .join(Unit, Slot.unit_id == Unit.id)
        .where(Unit.project_id == project_id)
        .group_by(Slot.status)
    ).all()
    counts = {"open": 0, "leased": 0, "filled": 0, "voided": 0}
    for status, count in rows:
        counts[status] = count
    return counts


def _per_batch(db: Session, project_id: int) -> list[dict[str, Any]]:
    batches = list(
        db.scalars(select(Batch).where(Batch.project_id == project_id).order_by(Batch.id))
    )
    # Unit status histogram per batch in one pass.
    rows = db.execute(
        select(Unit.batch_id, Unit.status, func.count())
        .where(Unit.project_id == project_id)
        .group_by(Unit.batch_id, Unit.status)
    ).all()
    hist: dict[int | None, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for batch_id, status, count in rows:
        hist[batch_id][status] = count

    out = []
    for batch in batches:
        h = hist.get(batch.id, {})
        total = sum(h.values())
        done = h.get("labeled", 0) + h.get("finalized", 0)
        out.append(
            {
                "batch_id": batch.id,
                "name": batch.name,
                "unit_count": batch.unit_count,
                "rejected_count": batch.rejected_count,
                "status_counts": dict(h),
                "done": done,
                "total": total,
                "fill_rate": round(done / total, 4) if total else 0.0,
            }
        )
    # Units with no batch (e.g. seeded directly) surface as a synthetic row so the
    # funnel and per-batch totals reconcile.
    if None in hist:
        h = hist[None]
        total = sum(h.values())
        done = h.get("labeled", 0) + h.get("finalized", 0)
        out.append(
            {
                "batch_id": None,
                "name": "(no batch)",
                "unit_count": total,
                "rejected_count": 0,
                "status_counts": dict(h),
                "done": done,
                "total": total,
                "fill_rate": round(done / total, 4) if total else 0.0,
            }
        )
    return out


def _per_variant(db: Session, project: Project) -> dict[str, Any]:
    """Filled-vs-total slot counts per variant value — the paired-bar proof of
    counterbalancing (§2.7, §11). Variant-free templates report a single bucket."""
    from app.models import Template

    template = db.get(Template, project.template_id)
    values = variant_values(template.schema) if template else None
    dimension = (
        template.schema.get("variants", {}).get("dimension") if template and values else None
    )

    rows = db.execute(
        select(Slot.variant, Slot.status, func.count())
        .join(Unit, Slot.unit_id == Unit.id)
        .where(Unit.project_id == project.id, Slot.status != "voided")
        .group_by(Slot.variant, Slot.status)
    ).all()

    buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for variant, status, count in rows:
        key = str(variant.get(dimension)) if dimension and variant else "_all"
        buckets[key][status] += count

    variants = []
    for value in values or ["_all"]:
        b = buckets.get(str(value), {})
        total = sum(b.values())
        filled = b.get("filled", 0)
        variants.append(
            {
                "value": None if value == "_all" else value,
                "filled": filled,
                "open": b.get("open", 0),
                "leased": b.get("leased", 0),
                "total": total,
                "fill_rate": round(filled / total, 4) if total else 0.0,
            }
        )
    # Balance holds iff every value has the same total (K/n each). Report it so the
    # UI can flag a broken invariant rather than the reader eyeballing the bars.
    totals = {v["total"] for v in variants if v["value"] is not None}
    balanced = len(totals) <= 1
    return {"dimension": dimension, "balanced": balanced, "values": variants}


def _consensus_rates(db: Session, project: Project) -> dict[str, Any]:
    """Per-key share of *complete* units that reached consensus, plus how many
    units are still short. Reads the cached snapshot where present."""
    units = list(
        db.scalars(select(Unit).where(Unit.project_id == project.id, Unit.is_gold.is_(False)))
    )
    agreed_by_key: dict[str, int] = defaultdict(int)
    total_by_key: dict[str, int] = defaultdict(int)
    complete_units = 0
    for unit in units:
        snapshot = unit.quality
        if snapshot is None:
            snapshot = evaluate_unit(db, unit, project).as_dict()
        if not snapshot.get("complete"):
            continue
        complete_units += 1
        for key, block in (snapshot.get("keys") or {}).items():
            total_by_key[key] += 1
            if block.get("agreed"):
                agreed_by_key[key] += 1
    keys = {
        key: {
            "agreed": agreed_by_key[key],
            "complete": total_by_key[key],
            "rate": round(agreed_by_key[key] / total_by_key[key], 4) if total_by_key[key] else None,
        }
        for key in sorted(total_by_key)
    }
    return {"complete_units": complete_units, "keys": keys}


def project_progress(
    db: Session,
    project_id: int,
    *,
    now: datetime | None = None,
    window_hours: float = DEFAULT_THROUGHPUT_WINDOW_HOURS,
) -> dict[str, Any]:
    """Assemble the full progress payload (§5 GET /projects/{id}/progress)."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")

    now = now or datetime.now(UTC)
    slot_counts = _slot_status_counts(db, project_id)
    remaining = slot_counts["open"] + slot_counts["leased"]

    submitted = list(
        db.scalars(
            select(Label.submitted_at)
            .join(Unit, Label.unit_id == Unit.id)
            .where(Unit.project_id == project_id, Label.is_valid.is_(True))
        )
    )

    return {
        "project_id": project_id,
        "labels_per_unit": project.labels_per_unit,
        "max_labels_per_unit": project.max_labels_per_unit,
        "funnel": _funnel(db, project_id),
        "slots": slot_counts,
        "labels_total": len(submitted),
        "batches": _per_batch(db, project_id),
        "variants": _per_variant(db, project),
        "consensus": _consensus_rates(db, project),
        "throughput": throughput(
            submitted, remaining, now=now, window_hours=window_hours
        ).as_dict(),
    }
