"""Quality tuning knobs (§6.1, §6.2), with per-project overrides.

Defaults live here; a project overrides any of them under ``config.quality``::

    "config": {"quality": {
        "gold_threshold": 0.7,      # rolling gold accuracy below this pauses
        "gold_window": 20,          # how many recent golds "rolling" means
        "gold_min_samples": 5,      # don't judge anyone on 1 gold
        "void_lookback": 20,        # labels voided when an annotator is paused
        "min_latency_ms": 1200,     # faster than this on a real task is a speed flag
        "on_disagreement": "grow_then_escalate"
    }}

Keeping them together (rather than scattered as literals) is what makes the M4
acceptance test — "below-threshold gold accuracy pauses an annotator" — writable
without a 20-label fixture: the test lowers the window and threshold instead.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class QualitySettings:
    gold_threshold: float = 0.7
    gold_window: int = 20
    gold_min_samples: int = 5
    void_lookback: int = 20
    min_latency_ms: int = 1200
    on_disagreement: str = "grow_then_escalate"
    # Composite reputation weights (§6.2): gold accuracy is dominant.
    weight_gold: float = 3.0
    weight_agreement: float = 1.0
    bias_penalty: float = 0.15
    speed_penalty: float = 0.10
    # Laplace smoothing so a brand-new annotator starts near 1.0 rather than 0.0
    # (min_reputation gating must not lock out everyone who hasn't seen a gold).
    prior_successes: float = 2.0
    prior_trials: float = 2.0


DEFAULTS = QualitySettings()

_FIELD_NAMES = {f.name for f in fields(QualitySettings)}


def quality_settings(project_config: dict[str, Any] | None) -> QualitySettings:
    """Resolve a project's quality settings, ignoring unknown keys."""
    overrides = ((project_config or {}).get("quality") or {}) if project_config else {}
    kwargs = {k: v for k, v in overrides.items() if k in _FIELD_NAMES}
    if not kwargs:
        return DEFAULTS
    return QualitySettings(**{**DEFAULTS.__dict__, **kwargs})
