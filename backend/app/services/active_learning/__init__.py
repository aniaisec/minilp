"""Active-learning loop (M9, §8) — "you train, MiniLP loops": training runs in
the user's own stack, and this package owns exactly the three things that are
MiniLP's job — selection, re-enrollment, and the eval curve.

No new tables, no new columns. Selection reads the consensus/entropy the
quality subsystem already computes; re-enrollment is M7's own versioning and
attachment; the eval curve reads gold accuracy and ``final_labels`` that
already exist. The loop closes entirely inside M1-M8's schema.
"""

from app.services.active_learning.checkpoints import register_checkpoint
from app.services.active_learning.iterations import agreement_vs_final, iteration_curve
from app.services.active_learning.selection import UnitScore, rank_batch, score_units

__all__ = [
    "UnitScore",
    "agreement_vs_final",
    "iteration_curve",
    "rank_batch",
    "register_checkpoint",
    "score_units",
]
