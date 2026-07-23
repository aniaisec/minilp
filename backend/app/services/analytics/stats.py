"""Small, pure statistical helpers for the analytics layer (§9, §11).

Kept database-free so the arithmetic can be pinned by hand-computed fixtures —
the same discipline ``services.quality.agreement`` follows. Nothing here imports
SQLAlchemy.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

# 95% two-sided normal quantile — the default for every CI reported by the API.
Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Interval:
    """A point estimate with a confidence interval."""

    estimate: float
    low: float
    high: float
    n: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "estimate": round(self.estimate, 4),
            "ci_low": round(self.low, 4),
            "ci_high": round(self.high, 4),
            "n": self.n,
        }


def token(value: Any) -> str:
    """A stable, JSON-safe string key for a canonical answer.

    Histograms key on the answer value, but a checkbox answer is a list and JSON
    object keys must be strings — so scalars render as themselves and everything
    else as canonical (sorted) JSON. Two equal answers always produce the same
    token, which is all a histogram needs.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def wilson_interval(successes: int, n: int, *, z: float = Z_95) -> Interval:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal (Wald) approximation because it stays inside [0, 1]
    and behaves at the extremes (0 or n successes) and for small n — exactly the
    regime a per-annotator bias score lives in. With ``n == 0`` the estimate is
    0.5 (maximally uninformative) over the full [0, 1] interval.
    """
    if n <= 0:
        return Interval(0.5, 0.0, 1.0, 0)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n)) / denom
    return Interval(p, max(0.0, center - margin), min(1.0, center + margin), n)


def bias_score(left: int, right: int) -> float | None:
    """How lopsided a two-sided split is, in [0, 1].

    0.0 is a perfect 50/50 split; 1.0 is always one side. Mirrors
    ``reputation.variant_bias`` so the number an annotator sees in their report
    and the number on the bias dashboard are the same definition. ``None`` when
    there are no positional votes to measure.
    """
    total = left + right
    if total == 0:
        return None
    return abs((left / total) - 0.5) * 2
