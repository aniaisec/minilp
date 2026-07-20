"""Per-key answer matching rules (§6.4).

One place decides "do these two answers for input key ``k`` agree?" — used by
gold grading (§6.1), consensus evaluation (§6.4) and agreement metrics (§6.3), so
a project's declared policy means the same thing everywhere::

    "agreement": {
      "category":      { "match": "exact",   "min_consensus": 0.67 },
      "fluency":       { "match": "within",  "tolerance": 1 },
      "quality_flags": { "match": "jaccard", "threshold": 0.5 }
    }

Rules are pure functions over canonical values (§2.8 ``label.value``), never over
raw input, so a positional click and the item it denotes never compare unequal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MATCH_KINDS = ("exact", "within", "jaccard")

DEFAULT_MIN_CONSENSUS = 0.67
DEFAULT_TOLERANCE = 1
DEFAULT_JACCARD_THRESHOLD = 0.5


class MatchError(ValueError):
    """An agreement policy entry is malformed."""


@dataclass(frozen=True)
class MatchRule:
    """A resolved per-key agreement policy."""

    match: str = "exact"
    tolerance: int | float = DEFAULT_TOLERANCE
    threshold: float = DEFAULT_JACCARD_THRESHOLD
    min_consensus: float = DEFAULT_MIN_CONSENSUS

    @classmethod
    def from_policy(cls, policy: dict[str, Any] | None) -> MatchRule:
        if not policy:
            return cls()
        match = policy.get("match", "exact")
        if match not in MATCH_KINDS:
            raise MatchError(f"unknown match kind '{match}' (expected one of {list(MATCH_KINDS)})")
        return cls(
            match=match,
            tolerance=policy.get("tolerance", DEFAULT_TOLERANCE),
            threshold=policy.get("threshold", DEFAULT_JACCARD_THRESHOLD),
            min_consensus=policy.get("min_consensus", DEFAULT_MIN_CONSENSUS),
        )


def rules_for(agreement: dict[str, Any] | None) -> dict[str, MatchRule]:
    """Resolve a project's ``agreement`` JSON into per-key rules."""
    if not agreement:
        return {}
    return {key: MatchRule.from_policy(policy) for key, policy in agreement.items()}


def rule_for(agreement: dict[str, Any] | None, key: str) -> MatchRule:
    """The rule for one input key; unlisted keys default to exact match."""
    if not agreement or key not in agreement:
        return MatchRule()
    return MatchRule.from_policy(agreement[key])


# --- the rules themselves ---------------------------------------------------


def _as_set(value: Any) -> set[Any]:
    if isinstance(value, list | tuple | set):
        return {_hashable(v) for v in value}
    return {_hashable(value)}


def _hashable(value: Any) -> Any:
    """Make dicts/lists comparable as set members (order-insensitive)."""
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    if isinstance(value, list | tuple):
        return tuple(_hashable(v) for v in value)
    return value


def jaccard(a: Any, b: Any) -> float:
    """Jaccard similarity of two multi-select answers. Two empties are identical."""
    sa, sb = _as_set(a), _as_set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    if not union:
        return 1.0
    return len(sa & sb) / len(union)


def values_match(a: Any, b: Any, rule: MatchRule) -> bool:
    """Do two canonical answers agree under ``rule``?

    ``exact``   — deep equality (lists compared order-insensitively, since a
                  checkbox answer is a set, not a sequence).
    ``within``  — numeric distance <= tolerance (likert ±1 counts as agreeing).
                  Non-numeric values fall back to exact so a malformed answer
                  can never silently "agree" with everything.
    ``jaccard`` — set overlap >= threshold.
    """
    if rule.match == "within":
        if isinstance(a, bool) or isinstance(b, bool):
            return a == b
        if isinstance(a, int | float) and isinstance(b, int | float):
            return abs(a - b) <= rule.tolerance
        return _hashable(a) == _hashable(b)
    if rule.match == "jaccard":
        return jaccard(a, b) >= rule.threshold
    # exact
    if isinstance(a, list) and isinstance(b, list):
        return _as_set(a) == _as_set(b) and len(a) == len(b)
    return _hashable(a) == _hashable(b)


def bucket_key(value: Any, rule: MatchRule) -> Any:
    """A hashable grouping key for vote tallying.

    Only sound for equivalence-style rules (``exact``); ``within``/``jaccard``
    are *not* transitive, so consensus for those is computed pairwise against a
    candidate rather than by bucketing (see ``consensus``).
    """
    return _hashable(value)
