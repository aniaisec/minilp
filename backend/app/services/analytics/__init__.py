"""Analytics layer (M5, §9/§11) — progress, bias, label distribution, unit detail.

Pure statistics live in ``stats``; every DB-facing entry point takes a ``Session``
and returns plain dicts ready to serialize, mirroring ``services.quality``.
"""

from app.services.analytics.bias import project_bias
from app.services.analytics.distribution import project_distribution
from app.services.analytics.progress import Throughput, project_progress, throughput
from app.services.analytics.roster import project_roster
from app.services.analytics.stats import Interval, bias_score, token, wilson_interval
from app.services.analytics.unit_detail import unit_detail

__all__ = [
    "Interval",
    "Throughput",
    "bias_score",
    "project_bias",
    "project_distribution",
    "project_progress",
    "project_roster",
    "throughput",
    "token",
    "unit_detail",
    "wilson_interval",
]
