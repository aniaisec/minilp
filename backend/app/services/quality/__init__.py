"""Quality subsystem (M4, §6) — golds, reputation, agreement, consensus.

Template- and annotator-kind-agnostic by construction: everything operates on
canonical JSON answers, so a human and a model judge are graded, scored and
counted toward agreement by the same code (principle 2).
"""

from app.services.quality.agreement import (
    cohens_kappa,
    fleiss_kappa,
    kappa,
    project_agreement,
    vote_entropy,
)
from app.services.quality.canonical import canonicalize
from app.services.quality.consensus import (
    apply_consensus_policy,
    evaluate_unit,
    grow_overlap,
    key_consensus,
)
from app.services.quality.gold import GoldGrade, grade_label
from app.services.quality.matching import MatchRule, jaccard, rule_for, values_match
from app.services.quality.pipeline import QualityOutcome, on_label_submitted
from app.services.quality.reputation import (
    annotator_report,
    compute_reputation,
    enforce_gold_threshold,
    gold_accuracy,
    pause_annotator,
    peer_agreement,
    record_event,
    refresh_reputation,
    resume_annotator,
    variant_bias,
)
from app.services.quality.thresholds import QualitySettings, quality_settings

__all__ = [
    "GoldGrade",
    "MatchRule",
    "QualityOutcome",
    "QualitySettings",
    "annotator_report",
    "apply_consensus_policy",
    "canonicalize",
    "cohens_kappa",
    "compute_reputation",
    "enforce_gold_threshold",
    "evaluate_unit",
    "fleiss_kappa",
    "gold_accuracy",
    "grade_label",
    "grow_overlap",
    "jaccard",
    "kappa",
    "key_consensus",
    "on_label_submitted",
    "pause_annotator",
    "peer_agreement",
    "project_agreement",
    "quality_settings",
    "record_event",
    "refresh_reputation",
    "resume_annotator",
    "rule_for",
    "values_match",
    "variant_bias",
    "vote_entropy",
]
