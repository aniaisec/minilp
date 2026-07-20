"""Gold grading (§6.1).

A gold unit carries ``gold_expected``: canonical expected answers keyed by input
id. It may grade a *subset* of the template's inputs — keys absent from
``gold_expected`` are simply not graded, so a template can have one objectively
correct field alongside subjective ones.

Grading compares canonical values with the project's per-key match rules (§6.4),
so a likert gold with ``{"match": "within", "tolerance": 1}`` accepts ±1 exactly
like consensus does. A label passes only when *every* graded key matches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.quality.matching import MatchRule, rule_for, values_match


@dataclass
class KeyGrade:
    key: str
    expected: Any
    actual: Any
    passed: bool
    match: str


@dataclass
class GoldGrade:
    """Outcome of grading one label against its unit's gold expectation."""

    graded: bool  # False when the unit isn't gold / has no expectations
    passed: bool
    keys: list[KeyGrade] = field(default_factory=list)

    @property
    def failed_keys(self) -> list[str]:
        return [k.key for k in self.keys if not k.passed]

    def as_detail(self) -> dict[str, Any]:
        """Compact JSON for the reputation event's ``detail`` column."""
        return {
            "passed": self.passed,
            "keys": {
                k.key: {"expected": k.expected, "actual": k.actual, "passed": k.passed}
                for k in self.keys
            },
        }


_MISSING = object()


def grade_label(
    gold_expected: dict[str, Any] | None,
    value: dict[str, Any],
    agreement: dict[str, Any] | None = None,
) -> GoldGrade:
    """Grade a canonical answer against a gold expectation.

    A graded key the annotator did not answer counts as a failure — a blank is
    not a free pass.
    """
    if not gold_expected:
        return GoldGrade(graded=False, passed=True)

    grades: list[KeyGrade] = []
    for key, expected in gold_expected.items():
        rule: MatchRule = rule_for(agreement, key)
        actual = value.get(key, _MISSING)
        if actual is _MISSING:
            grades.append(
                KeyGrade(key=key, expected=expected, actual=None, passed=False, match=rule.match)
            )
            continue
        grades.append(
            KeyGrade(
                key=key,
                expected=expected,
                actual=actual,
                passed=values_match(actual, expected, rule),
                match=rule.match,
            )
        )

    return GoldGrade(
        graded=bool(grades),
        passed=all(g.passed for g in grades),
        keys=grades,
    )
