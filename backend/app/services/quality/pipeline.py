"""The quality pipeline (§6, principle 5: *quality is a pipeline, not a report*).

One entry point, ``on_label_submitted``, runs after every label lands and does, in
order:

1. **Canonicalize** server-side (§2.6) — the stored ``value`` is ours, not the
   client's.
2. **Grade golds** (§6.1) — record pass/fail on the label and a reputation event.
3. **Speed flag** (§6.2) — implausibly fast human submissions.
4. **Refresh reputation** (§6.2) and **enforce the gold threshold** — a
   below-threshold annotator is paused and their recent work voided.
5. **Evaluate consensus** (§6.4) on the unit — grow overlap or escalate.

Ordering matters: pausing voids labels (including, possibly, the one just
submitted), so consensus is evaluated last, against the surviving set.

The assignment engine calls this; it never reaches into quality internals, and
quality never touches slots except via ``slots.lifecycle`` — which is what keeps
the §2.7 balance invariant true through every quality action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models import Annotator, Label, Project, Slot, Template, Unit
from app.services.quality.canonical import canonicalize
from app.services.quality.consensus import ConsensusResult, apply_consensus_policy
from app.services.quality.gold import GoldGrade, grade_label
from app.services.quality.reputation import (
    enforce_gold_threshold,
    record_event,
    refresh_reputation,
)
from app.services.quality.thresholds import quality_settings


@dataclass
class QualityOutcome:
    """What the pipeline did — returned so the API can surface it (blindly)."""

    gold: GoldGrade | None = None
    paused: bool = False
    labels_voided: int = 0
    reputation: float | None = None
    consensus: ConsensusResult | None = None
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gold_graded": bool(self.gold and self.gold.graded),
            "paused": self.paused,
            "labels_voided": self.labels_voided,
            "reputation": self.reputation,
            "flags": self.flags,
            "consensus": self.consensus.as_dict() if self.consensus else None,
        }


def canonicalize_label(db: Session, label: Label) -> dict[str, Any]:
    """Recompute ``label.value`` from ``label.raw`` and the slot's variant."""
    unit = db.get(Unit, label.unit_id)
    if unit is None:
        return label.value
    project = db.get(Project, unit.project_id)
    template = db.get(Template, project.template_id) if project else None
    if template is None:
        return label.value
    slot = db.get(Slot, label.slot_id)
    label.value = canonicalize(template.schema, label.raw, slot.variant if slot else None)
    db.flush()
    return label.value


def on_label_submitted(db: Session, label: Label) -> QualityOutcome:
    """Run the full quality pipeline for a freshly submitted label."""
    outcome = QualityOutcome()

    unit = db.get(Unit, label.unit_id)
    if unit is None:
        return outcome
    project = db.get(Project, unit.project_id)
    if project is None:
        return outcome
    cfg = quality_settings(project.config)

    # 1. Server-side canonicalization (§2.6).
    canonicalize_label(db, label)

    # 2. Gold grading (§6.1).
    if unit.is_gold:
        grade = grade_label(unit.gold_expected, label.value, project.agreement)
        outcome.gold = grade
        if grade.graded:
            label.gold_passed = grade.passed
            record_event(
                db,
                label.annotator_id,
                "gold_pass" if grade.passed else "gold_fail",
                delta=1.0 if grade.passed else -1.0,
                detail={"unit_id": unit.id, **grade.as_detail()},
            )
            db.flush()

    # 3. Speed flag (humans only — a judge answering in 200ms is expected).
    annotator = db.get(Annotator, label.annotator_id)
    if (
        annotator is not None
        and annotator.kind == "human"
        and label.latency_ms is not None
        and label.latency_ms < cfg.min_latency_ms
    ):
        record_event(
            db,
            label.annotator_id,
            "speed_flag",
            delta=0.0,
            detail={"unit_id": unit.id, "latency_ms": label.latency_ms},
        )
        outcome.flags.append("speed")

    # 4. Reputation refresh + gold-threshold enforcement (§6.1, §6.2).
    if unit.is_gold and outcome.gold and outcome.gold.graded and not outcome.gold.passed:
        voided = enforce_gold_threshold(db, label.annotator_id, project, settings=cfg)
        if voided or (annotator is not None and annotator.status == "paused"):
            outcome.paused = True
            outcome.labels_voided = voided
    breakdown = refresh_reputation(db, label.annotator_id, project_id=project.id, settings=cfg)
    outcome.reputation = round(breakdown.score, 4)

    # 5. Consensus / dynamic overlap growth (§6.4) — after any voiding above.
    db.refresh(unit)
    outcome.consensus = apply_consensus_policy(db, unit, project)
    return outcome
