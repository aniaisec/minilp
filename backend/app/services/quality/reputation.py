"""Reputation engine (§6.2) — one composite score in [0, 1], recomputed on every
``reputation_event``, that the assignment engine gates on and (from M7) doubles as
a judge's merge weight.

Components, in the order §6.2 ranks them:

1. **Gold accuracy** (dominant) — rolling over the annotator's most recent
   ``gold_window`` gold labels, Laplace-smoothed so a new annotator starts near
   1.0 instead of at 0.0 (a cold 0.0 would lock everyone out of a project with
   ``min_reputation > 0`` before they had a chance to answer a gold).
2. **Peer agreement** — how often the annotator's canonical answer matches the
   majority on units that collected multiple labels.
3. **Variant-bias penalty** — for positional templates only, how far their
   left/right split departs from 50/50 (§9).
4. **Speed flags** (humans only) — submissions faster than plausible reading time.

Nothing here mutates slots except through ``slots.lifecycle``, so the §2.7 balance
invariant holds when a failing annotator's work is voided.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Annotator, Label, Project, ReputationEvent, Slot, Unit
from app.services.quality.matching import _hashable, rule_for, values_match
from app.services.quality.thresholds import QualitySettings, quality_settings
from app.services.slots.lifecycle import void_labels

# Raw positional answers whose split measures order bias (§9).
_LEFT = {"left", "a", "first"}
_RIGHT = {"right", "b", "second"}


@dataclass
class Component:
    value: float | None
    n: int


@dataclass
class ReputationBreakdown:
    """Why an annotator's score is what it is — surfaced by /annotators/{id}/report."""

    score: float
    gold: Component
    agreement: Component
    bias: Component
    speed_flags: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "gold_accuracy": self.gold.value,
            "gold_samples": self.gold.n,
            "peer_agreement": self.agreement.value,
            "agreement_samples": self.agreement.n,
            "variant_bias": self.bias.value,
            "bias_samples": self.bias.n,
            "speed_flags": self.speed_flags,
        }


# --- events -----------------------------------------------------------------


def record_event(
    db: Session,
    annotator_id: int,
    kind: str,
    *,
    delta: float = 0.0,
    detail: dict[str, Any] | None = None,
) -> ReputationEvent:
    """Append a reputation event (the log is the source of truth; the score on
    ``annotators`` is a materialized cache of it)."""
    event = ReputationEvent(annotator_id=annotator_id, kind=kind, delta=delta, detail=detail)
    db.add(event)
    db.flush()
    return event


# --- components -------------------------------------------------------------


def gold_accuracy(
    db: Session,
    annotator_id: int,
    *,
    project_id: int | None = None,
    window: int = 20,
) -> tuple[int, int]:
    """(passes, total) over the annotator's most recent ``window`` graded golds.

    Only valid labels count — voiding a paused annotator's work also removes it
    from their own rolling accuracy, which is what makes an unpause meaningful.
    """
    stmt = (
        select(Label.gold_passed)
        .join(Unit, Label.unit_id == Unit.id)
        .where(
            Label.annotator_id == annotator_id,
            Label.is_valid.is_(True),
            Label.gold_passed.is_not(None),
        )
        .order_by(desc(Label.submitted_at), desc(Label.id))
        .limit(window)
    )
    if project_id is not None:
        stmt = stmt.where(Unit.project_id == project_id)
    results = list(db.scalars(stmt))
    return sum(1 for r in results if r), len(results)


def peer_agreement(
    db: Session, annotator_id: int, *, project_id: int | None = None
) -> tuple[int, int]:
    """(agreements, comparisons) of this annotator's answers vs. the peer majority.

    Compared per input key on canonical values under the project's match rules, so
    a likert ±1 policy counts near-misses as agreement here exactly as it does in
    consensus (§6.4).
    """
    stmt = (
        select(Label.unit_id)
        .join(Unit, Label.unit_id == Unit.id)
        .where(Label.annotator_id == annotator_id, Label.is_valid.is_(True))
    )
    if project_id is not None:
        stmt = stmt.where(Unit.project_id == project_id)
    unit_ids = list(db.scalars(stmt))
    if not unit_ids:
        return 0, 0

    agreements = comparisons = 0
    for unit_id in unit_ids:
        unit = db.get(Unit, unit_id)
        if unit is None:
            continue
        project = db.get(Project, unit.project_id)
        peers = list(
            db.scalars(
                select(Label).where(
                    Label.unit_id == unit_id,
                    Label.is_valid.is_(True),
                    Label.annotator_id != annotator_id,
                )
            )
        )
        if not peers:
            continue
        mine = db.scalar(
            select(Label).where(
                Label.unit_id == unit_id,
                Label.annotator_id == annotator_id,
                Label.is_valid.is_(True),
            )
        )
        if mine is None:
            continue
        for key, my_value in (mine.value or {}).items():
            peer_values = [
                p.value[key] for p in peers if isinstance(p.value, dict) and key in p.value
            ]
            if not peer_values:
                continue
            rule = rule_for(project.agreement if project else None, key)
            majority, _ = Counter(_hashable(v) for v in peer_values).most_common(1)[0]
            comparisons += 1
            if values_match(my_value, majority, rule):
                agreements += 1
    return agreements, comparisons


def variant_bias(
    db: Session, annotator_id: int, *, project_id: int | None = None
) -> tuple[float | None, int]:
    """(bias in [0, 1], n) — how lopsided this annotator's left/right split is.

    0.0 is a perfect 50/50 split, 1.0 is always picking the same side. Ties and
    non-positional answers are excluded; a template without positional inputs
    yields ``(None, 0)`` and drops out of the composite entirely.
    """
    stmt = (
        select(Label.raw)
        .join(Unit, Label.unit_id == Unit.id)
        .join(Slot, Label.slot_id == Slot.id)
        .where(
            Label.annotator_id == annotator_id,
            Label.is_valid.is_(True),
            Slot.variant.is_not(None),
        )
    )
    if project_id is not None:
        stmt = stmt.where(Unit.project_id == project_id)

    left = right = 0
    for raw in db.scalars(stmt):
        for value in (raw or {}).values():
            if not isinstance(value, str):
                continue
            token = value.strip().lower()
            if token in _LEFT:
                left += 1
            elif token in _RIGHT:
                right += 1
    total = left + right
    if total == 0:
        return None, 0
    return abs((left / total) - 0.5) * 2, total


def speed_flag_count(db: Session, annotator_id: int) -> int:
    return len(
        list(
            db.scalars(
                select(ReputationEvent.id).where(
                    ReputationEvent.annotator_id == annotator_id,
                    ReputationEvent.kind == "speed_flag",
                )
            )
        )
    )


# --- composite --------------------------------------------------------------


def compute_reputation(
    db: Session,
    annotator_id: int,
    *,
    project_id: int | None = None,
    settings: QualitySettings | None = None,
) -> ReputationBreakdown:
    """Recompute the composite score without writing it."""
    from app.services.quality.thresholds import DEFAULTS

    cfg = settings or DEFAULTS
    annotator = db.get(Annotator, annotator_id)

    passes, gold_n = gold_accuracy(db, annotator_id, project_id=project_id, window=cfg.gold_window)
    gold_rate = (passes + cfg.prior_successes) / (gold_n + cfg.prior_trials)

    agreed, comparisons = peer_agreement(db, annotator_id, project_id=project_id)
    agreement_rate = (agreed / comparisons) if comparisons else None

    bias, bias_n = variant_bias(db, annotator_id, project_id=project_id)
    flags = speed_flag_count(db, annotator_id)

    # Weighted mean of the components that actually have data. Gold always has
    # data thanks to the prior, so the score is never undefined.
    num = cfg.weight_gold * gold_rate
    den = cfg.weight_gold
    if agreement_rate is not None:
        num += cfg.weight_agreement * agreement_rate
        den += cfg.weight_agreement
    score = num / den

    if bias is not None:
        score -= cfg.bias_penalty * bias
    if annotator is not None and annotator.kind == "human" and flags:
        # Saturating: repeated flags shouldn't drive the score arbitrarily negative.
        score -= cfg.speed_penalty * min(1.0, flags / 5)

    score = max(0.0, min(1.0, score))
    return ReputationBreakdown(
        score=score,
        gold=Component(round(passes / gold_n, 4) if gold_n else None, gold_n),
        agreement=Component(
            round(agreement_rate, 4) if agreement_rate is not None else None, comparisons
        ),
        bias=Component(round(bias, 4) if bias is not None else None, bias_n),
        speed_flags=flags,
    )


def refresh_reputation(
    db: Session,
    annotator_id: int,
    *,
    project_id: int | None = None,
    settings: QualitySettings | None = None,
) -> ReputationBreakdown:
    """Recompute and persist ``annotators.reputation_score``."""
    breakdown = compute_reputation(db, annotator_id, project_id=project_id, settings=settings)
    annotator = db.get(Annotator, annotator_id)
    if annotator is not None:
        annotator.reputation_score = breakdown.score
        db.flush()
    return breakdown


# --- pausing ----------------------------------------------------------------


def recent_labels(db: Session, annotator_id: int, project_id: int, limit: int) -> list[Label]:
    """The annotator's most recent valid labels in a project, newest first."""
    return list(
        db.scalars(
            select(Label)
            .join(Unit, Label.unit_id == Unit.id)
            .where(
                Label.annotator_id == annotator_id,
                Label.is_valid.is_(True),
                Unit.project_id == project_id,
            )
            .order_by(desc(Label.submitted_at), desc(Label.id))
            .limit(limit)
        )
    )


def pause_annotator(
    db: Session,
    annotator_id: int,
    project_id: int,
    *,
    reason: str,
    settings: QualitySettings | None = None,
) -> int:
    """Pause an annotator and void their recent work (§6.1).

    Voided labels' slots reopen **retaining their variant**, so the unit can be
    re-collected in balance — the acceptance criterion for M4. Returns the number
    of labels voided.
    """
    from app.services.quality.thresholds import DEFAULTS

    cfg = settings or DEFAULTS
    annotator = db.get(Annotator, annotator_id)
    if annotator is None:
        return 0

    annotator.status = "paused"
    annotator.pause_reason = reason
    labels = recent_labels(db, annotator_id, project_id, cfg.void_lookback)
    voided = void_labels(db, labels)
    record_event(
        db,
        annotator_id,
        "gold_fail",
        delta=0.0,
        detail={"action": "paused", "reason": reason, "labels_voided": voided},
    )
    refresh_reputation(db, annotator_id, project_id=project_id, settings=cfg)
    return voided


def resume_annotator(db: Session, annotator_id: int) -> Annotator | None:
    """Clear a pause (admin action, §5). Voided work stays voided."""
    annotator = db.get(Annotator, annotator_id)
    if annotator is None:
        return None
    annotator.status = "active"
    annotator.pause_reason = None
    db.flush()
    return annotator


def enforce_gold_threshold(
    db: Session,
    annotator_id: int,
    project: Project,
    *,
    settings: QualitySettings | None = None,
) -> int:
    """Pause the annotator if rolling gold accuracy has fallen below threshold.

    Returns the number of labels voided (0 when no action was taken). Requires
    ``gold_min_samples`` graded golds first — nobody is paused on one unlucky
    answer.
    """
    cfg = settings or quality_settings(project.config)
    passes, total = gold_accuracy(db, annotator_id, project_id=project.id, window=cfg.gold_window)
    if total < cfg.gold_min_samples:
        return 0
    accuracy = passes / total
    if accuracy >= cfg.gold_threshold:
        return 0
    return pause_annotator(
        db,
        annotator_id,
        project.id,
        reason=(
            f"gold accuracy {accuracy:.2f} over last {total} golds "
            f"is below threshold {cfg.gold_threshold:.2f}"
        ),
        settings=cfg,
    )


def annotator_report(
    db: Session, annotator_id: int, *, project_id: int | None = None
) -> dict[str, Any]:
    """Reputation/calibration history for ``GET /annotators/{id}/report`` (§5)."""
    annotator = db.get(Annotator, annotator_id)
    if annotator is None:
        raise ValueError(f"annotator {annotator_id} not found")

    breakdown = compute_reputation(db, annotator_id, project_id=project_id)
    events = list(
        db.scalars(
            select(ReputationEvent)
            .where(ReputationEvent.annotator_id == annotator_id)
            .order_by(desc(ReputationEvent.created_at), desc(ReputationEvent.id))
            .limit(50)
        )
    )
    return {
        "annotator_id": annotator.id,
        "kind": annotator.kind,
        "display_name": annotator.display_name,
        "status": annotator.status,
        "pause_reason": annotator.pause_reason,
        "reputation_score": round(annotator.reputation_score, 4),
        "live": breakdown.as_dict(),
        "events": [
            {
                "id": e.id,
                "kind": e.kind,
                "delta": e.delta,
                "detail": e.detail,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }
