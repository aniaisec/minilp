"""Informativeness ranking + batch selection (§8 step 1).

"You train, MiniLP loops": training happens in the user's own stack, and this
module owns exactly the "which units next" decision — nothing here trains
anything or calls a model.

Three signals, each computed from data the quality subsystem already produces
(§6.3/§6.4), combined the way ``reputation.compute_reputation`` combines its
own components — a weighted mean over whichever signals a unit actually has,
so a brand-new unit with none of them yet doesn't crash the ranking, it just
sits at the neutral midpoint and loses ties to units with real evidence:

    disagreement  1 − the worst key's consensus rate (§6.4) — an ensemble that
                  can't agree with itself is exactly what a human/gold pass
                  should look at next.
    entropy       mean per-key vote entropy (§6.3) — ``vote_entropy`` already
                  says in its own docstring that this is what "drives
                  escalation (§7.2) and active learning (§8)".
    confidence    1 − the *current student model's own* reported confidence on
                  this unit, read from its ``labels.confidence`` (§7.1) if it
                  has already labeled the unit. This is the classic
                  uncertainty-sampling signal and the only one of the three
                  that needs a ``judge_config_id`` — omit it and the ranking
                  falls back to ensemble disagreement/entropy alone.

A unit that already has a ``final_labels`` row is decided and is dropped from
the pool before scoring — there is nothing left to be informative *about*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotator, FinalLabel, JudgeConfig, Label, Project, Unit
from app.services.quality.consensus import evaluate_unit

__all__ = ["UnitScore", "score_units", "rank_batch"]


@dataclass
class UnitScore:
    unit_id: int
    priority: int
    disagreement: float | None
    entropy: float | None
    confidence: float | None  # the student model's own reported confidence, raw
    score: float
    kept: bool = True  # survives diversity de-duping (§8 "optional embedding-diversity de-duping")

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "priority": self.priority,
            "disagreement": round(self.disagreement, 4) if self.disagreement is not None else None,
            "entropy": round(self.entropy, 4) if self.entropy is not None else None,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "score": round(self.score, 4),
        }


_NEUTRAL = 0.5  # score for a unit with no signal yet — see module docstring


def _consensus_signal(
    db: Session, unit: Unit, project: Project
) -> tuple[float | None, float | None]:
    """(disagreement, mean_entropy) from the unit's own collected labels, or
    ``(None, None)`` when it has none yet."""
    result = evaluate_unit(db, unit, project)
    if not result.keys:
        return None, None
    worst_rate = min(k.rate for k in result.keys)
    mean_entropy = sum(k.entropy for k in result.keys) / len(result.keys)
    return 1.0 - worst_rate, mean_entropy


def _confidence_signal(db: Session, unit: Unit, annotator_id: int | None) -> float | None:
    if annotator_id is None:
        return None
    label = db.scalar(
        select(Label).where(
            Label.unit_id == unit.id, Label.annotator_id == annotator_id, Label.is_valid.is_(True)
        )
    )
    return label.confidence if label is not None else None


def _score(disagreement: float | None, entropy: float | None, confidence: float | None) -> float:
    components = [c for c in (disagreement, entropy) if c is not None]
    if confidence is not None:
        components.append(1.0 - confidence)
    if not components:
        return _NEUTRAL
    return sum(components) / len(components)


def score_units(
    db: Session,
    project: Project,
    *,
    judge_config_id: int | None = None,
) -> list[UnitScore]:
    """Score every unfinalized unit in ``project``. Unsorted — see ``rank_batch``."""
    annotator_id: int | None = None
    if judge_config_id is not None:
        annotator_id = db.scalar(
            select(Annotator.id).where(Annotator.judge_config_id == judge_config_id)
        )

    # A finalized unit is decided; nothing left to be informative about (module
    # docstring). A correlated NOT EXISTS reads correctly whether or not any
    # unit in the project has been finalized yet.
    not_finalized = ~select(FinalLabel.id).where(FinalLabel.unit_id == Unit.id).exists()
    units = db.scalars(select(Unit).where(Unit.project_id == project.id, not_finalized))

    scores: list[UnitScore] = []
    for unit in units:
        disagreement, entropy = _consensus_signal(db, unit, project)
        confidence = _confidence_signal(db, unit, annotator_id)
        scores.append(
            UnitScore(
                unit_id=unit.id,
                priority=unit.priority or 0,
                disagreement=disagreement,
                entropy=entropy,
                confidence=confidence,
                score=_score(disagreement, entropy, confidence),
            )
        )
    return scores


def _vector(unit_payload: dict[str, Any], field_name: str) -> list[float] | None:
    value = unit_payload.get(field_name)
    if not isinstance(value, list) or not value:
        return None
    try:
        return [float(v) for v in value]
    except (TypeError, ValueError):
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _dedupe(
    db: Session, ordered: list[UnitScore], *, dedupe_field: str, dedupe_threshold: float
) -> None:
    """Greedily drop units too similar to a higher-scored unit already kept.

    Mutates ``kept`` in place. A unit whose payload has no usable vector under
    ``dedupe_field`` is always kept — de-duping is best-effort, not a filter
    that can silently empty the batch because of missing embeddings.
    """
    kept_vectors: list[list[float]] = []
    for entry in ordered:
        unit = db.get(Unit, entry.unit_id)
        vector = _vector(unit.payload or {}, dedupe_field) if unit else None
        if vector is None:
            continue
        if any(_cosine(vector, kv) >= dedupe_threshold for kv in kept_vectors):
            entry.kept = False
            continue
        kept_vectors.append(vector)


def rank_batch(
    db: Session,
    project_id: int,
    *,
    limit: int = 20,
    judge_config_id: int | None = None,
    dedupe_field: str | None = None,
    dedupe_threshold: float = 0.85,
) -> dict[str, Any]:
    """The next most-informative batch for ``project`` (§5 ``GET
    /projects/{id}/active-learning/batch``, §8 step 1)."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")
    if judge_config_id is not None and db.get(JudgeConfig, judge_config_id) is None:
        raise ValueError(f"judge config {judge_config_id} not found")

    scores = score_units(db, project, judge_config_id=judge_config_id)
    scores.sort(key=lambda s: (-s.score, -s.priority, s.unit_id))

    if dedupe_field:
        _dedupe(db, scores, dedupe_field=dedupe_field, dedupe_threshold=dedupe_threshold)

    batch = [s for s in scores if s.kept][:limit]
    return {
        "project_id": project_id,
        "judge_config_id": judge_config_id,
        "pool_size": len(scores),
        "dropped_by_dedupe": sum(1 for s in scores if not s.kept),
        "units": [s.as_dict() for s in batch],
    }
