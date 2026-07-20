"""Per-key match rules, canonicalization and gold grading (§6.1, §6.4).

Pure — no database — so these run everywhere, including on a machine with no
PostgreSQL.
"""

import pytest

from app.services.quality.canonical import canonicalize, canonicalize_positional
from app.services.quality.gold import grade_label
from app.services.quality.matching import (
    MatchError,
    MatchRule,
    jaccard,
    rule_for,
    rules_for,
    values_match,
)

# --- rule resolution --------------------------------------------------------


def test_unlisted_key_defaults_to_exact():
    rule = rule_for({"category": {"match": "jaccard"}}, "something_else")
    assert rule.match == "exact"


def test_policy_round_trips():
    rules = rules_for(
        {
            "category": {"match": "exact", "min_consensus": 0.67},
            "fluency": {"match": "within", "tolerance": 1},
            "quality_flags": {"match": "jaccard", "threshold": 0.5},
        }
    )
    assert rules["category"].min_consensus == 0.67
    assert rules["fluency"].tolerance == 1
    assert rules["quality_flags"].threshold == 0.5


def test_unknown_match_kind_is_rejected():
    with pytest.raises(MatchError):
        rule_for({"k": {"match": "vibes"}}, "k")


# --- exact ------------------------------------------------------------------


def test_exact_matches_scalars_and_is_order_insensitive_for_lists():
    exact = MatchRule()
    assert values_match("cat", "cat", exact)
    assert not values_match("cat", "dog", exact)
    # A checkbox answer is a set, not a sequence.
    assert values_match(["a", "b"], ["b", "a"], exact)
    assert not values_match(["a", "b"], ["a"], exact)


# --- within -----------------------------------------------------------------


def test_within_tolerance_accepts_adjacent_likert():
    rule = MatchRule(match="within", tolerance=1)
    assert values_match(4, 5, rule)
    assert values_match(4, 4, rule)
    assert not values_match(3, 5, rule)


def test_within_falls_back_to_exact_for_non_numeric():
    """A tolerance rule must never make two strings 'agree' by accident."""
    rule = MatchRule(match="within", tolerance=1)
    assert values_match("good", "good", rule)
    assert not values_match("good", "bad", rule)


def test_within_does_not_treat_bools_as_numbers():
    rule = MatchRule(match="within", tolerance=1)
    assert not values_match(True, 0, rule)  # would be |1-0| <= 1 numerically


# --- jaccard ----------------------------------------------------------------


def test_jaccard_similarity_values():
    assert jaccard(["a", "b"], ["a", "b"]) == 1.0
    assert jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)
    assert jaccard([], []) == 1.0
    assert jaccard(["a"], []) == 0.0


def test_jaccard_threshold():
    rule = MatchRule(match="jaccard", threshold=0.5)
    assert values_match(["a", "b"], ["a", "b", "c"], rule)  # 2/3
    assert not values_match(["a"], ["b", "c"], rule)  # 0


# --- canonicalization (§2.6) ------------------------------------------------

SIDE_BY_SIDE = {
    "name": "sbs",
    "inputs": [{"id": "choice", "type": "choice_buttons", "options": ["Left", "Tie", "Right"]}],
    "variants": {"dimension": "panel_order", "values": ["AB", "BA"]},
}

IMAGE_CLS = {
    "name": "img",
    "inputs": [{"id": "category", "type": "radio", "options": ["cat", "dog"], "allow_other": True}],
    "variants": None,
}


def test_positional_canonicalization_follows_the_variant():
    assert canonicalize_positional("Left", "AB") == "A"
    assert canonicalize_positional("Left", "BA") == "B"
    assert canonicalize_positional("Right", "BA") == "A"
    assert canonicalize_positional("Tie", "BA") == "Tie"


def test_canonicalize_side_by_side_under_flipped_variant():
    value = canonicalize(SIDE_BY_SIDE, {"choice": "Left"}, {"panel_order": "BA"})
    assert value == {"choice": "B"}


def test_canonicalize_strips_the_other_prefix():
    assert canonicalize(IMAGE_CLS, {"category": "other:capybara"}, None) == {"category": "capybara"}


def test_canonicalize_is_identity_without_variant_or_other():
    raw = {"category": "cat"}
    assert canonicalize(IMAGE_CLS, raw, None) == raw


def test_canonicalize_passes_unknown_keys_through():
    assert canonicalize(IMAGE_CLS, {"stray": 1}, None) == {"stray": 1}


# --- gold grading (§6.1) ----------------------------------------------------


def test_gold_grade_passes_when_every_graded_key_matches():
    grade = grade_label({"category": "cat"}, {"category": "cat", "notes": "x"})
    assert grade.graded and grade.passed


def test_gold_grades_only_the_keys_it_declares():
    """A gold may grade a subset of inputs (§6.1) — ungraded keys are free."""
    grade = grade_label({"category": "cat"}, {"category": "cat", "confidence": 1})
    assert grade.passed
    assert [k.key for k in grade.keys] == ["category"]


def test_gold_grade_fails_on_any_key():
    grade = grade_label(
        {"category": "cat", "quality": "high"}, {"category": "cat", "quality": "low"}
    )
    assert not grade.passed
    assert grade.failed_keys == ["quality"]


def test_gold_grade_uses_the_projects_match_rule():
    agreement = {"fluency": {"match": "within", "tolerance": 1}}
    assert grade_label({"fluency": 4}, {"fluency": 5}, agreement).passed
    assert not grade_label({"fluency": 4}, {"fluency": 5}).passed  # exact by default


def test_missing_answer_on_a_graded_key_fails():
    grade = grade_label({"category": "cat"}, {})
    assert grade.graded and not grade.passed


def test_non_gold_unit_is_not_graded():
    grade = grade_label(None, {"category": "cat"})
    assert not grade.graded and grade.passed
