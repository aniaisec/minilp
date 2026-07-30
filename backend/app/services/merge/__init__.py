"""Merge & routing (M8, §7.2).

The half of the platform that turns *labels* into *a label*: a
calibration-weighted merge of everyone's votes, a declarative pipeline that
decides whether the merge is good enough to stand on its own, and a review queue
for the units where it isn't.

Layering, deliberately one-directional:

    merge.py    reads labels          → a proposal (pure, no writes)
    finalize.py writes final_labels   → the decided answer + project.completed
    pipeline.py orchestrates stages   → auto-finalize or escalate
    review.py   humans decide         → human_approved / human_override

``merge`` depends on ``quality`` (match rules, entropy) and never the other way
round except at the single call site in ``quality.pipeline`` that runs routing
after consensus — which is the point where "quality is a pipeline, not a report"
(principle 5) reaches its last stage.
"""

from app.services.merge.condition import ConditionError, evaluate_condition
from app.services.merge.finalize import (
    check_project_completed,
    final_label_for,
    finalize_unit,
    unfinalized_count,
)
from app.services.merge.merge import MergeResult, merge_unit
from app.services.merge.pipeline import (
    DEFAULT_PIPELINE,
    PipelineError,
    RoutingResult,
    effective_pipeline,
    register_stage,
    registered_stages,
    route_unit,
    validate_pipeline,
)
from app.services.merge.review import (
    ReviewError,
    backlog_threshold,
    check_backlog,
    decide,
    queue_depth,
    review_item,
    review_queue,
)
from app.services.merge.weights import MIN_WEIGHT, merge_weight

__all__ = [
    "DEFAULT_PIPELINE",
    "MIN_WEIGHT",
    "ConditionError",
    "MergeResult",
    "PipelineError",
    "ReviewError",
    "RoutingResult",
    "backlog_threshold",
    "check_backlog",
    "check_project_completed",
    "decide",
    "effective_pipeline",
    "evaluate_condition",
    "final_label_for",
    "finalize_unit",
    "merge_unit",
    "merge_weight",
    "queue_depth",
    "register_stage",
    "registered_stages",
    "review_item",
    "review_queue",
    "route_unit",
    "unfinalized_count",
    "validate_pipeline",
]
