"""Merge weights (§7.2) — "weights = live reputation".

§6.2 ends with the sentence this module implements: *"A judge's reputation is its
calibration score and doubles as its merge weight."* There is deliberately no
second scoring system here; anything that moves reputation (gold accuracy, peer
agreement, variant bias) moves merge weight in the same breath, which is what
makes "synthetic judges with known accuracies → merge weights converge" a
statement about the product rather than about this file.

Two judgement calls, stated rather than buried:

**A floor, not a zero.** A brand-new rater with no graded golds sits near the
Laplace-smoothed prior, not at 0.0 (§6.2) — but a rater who has genuinely earned
0.0 would otherwise be *silently deleted* from the merge, and a unit whose only
voter is discredited would merge to "unanimous" with no votes. ``MIN_WEIGHT``
keeps such a vote countable-but-negligible so the arithmetic stays honest and the
provenance still records who spoke.

**Weights are read live, never cached.** A merge recomputed tomorrow with better
calibration data should produce a better answer; freezing weights onto the label
row would make yesterday's mistake permanent. The *provenance* of a finalized
label does record the weights used at decision time (§7.2), so the decision stays
explainable even after the weights move.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotator

__all__ = ["MIN_WEIGHT", "merge_weight", "weights_for"]

# The smallest weight a vote can carry. Small enough that a discredited rater
# cannot outvote a calibrated one (0.05 vs ~0.9 is 18:1), large enough that a
# unit voted on only by discredited raters still merges to *something* with a
# visibly low confidence rather than dividing by zero.
MIN_WEIGHT = 0.05


def merge_weight(annotator: Annotator | None) -> float:
    """This annotator's weight in a calibration-weighted merge.

    A missing annotator (deleted mid-flight) weighs the floor rather than raising:
    a merge is a read-side computation and must not fail because of referential
    housekeeping.
    """
    if annotator is None:
        return MIN_WEIGHT
    return max(MIN_WEIGHT, min(1.0, float(annotator.reputation_score or 0.0)))


def weights_for(db: Session, annotator_ids: Iterable[int]) -> dict[int, float]:
    """Weights for a set of annotators in one query (merge is per-unit, in a loop)."""
    ids = list({int(a) for a in annotator_ids})
    if not ids:
        return {}
    rows = db.scalars(select(Annotator).where(Annotator.id.in_(ids)))
    return {a.id: merge_weight(a) for a in rows}
