"""Agreement metrics against hand-computed fixtures (§6.3, M4 acceptance).

Every expected number below is derived in the docstring from the definition, so a
regression in the arithmetic is caught by a value a reader can verify by hand —
which is the point of the acceptance criterion "kappa matches hand-computed
fixtures".
"""

import math

import pytest

from app.services.quality.agreement import (
    cohens_kappa,
    fleiss_kappa,
    kappa,
    vote_entropy,
)
from app.services.quality.consensus import key_consensus
from app.services.quality.matching import MatchRule

# --- Cohen's kappa (K = 2) --------------------------------------------------


def test_cohens_kappa_textbook_fixture():
    """50 items, two raters:

        both yes 20 | A yes,B no  5
        A no,B yes 10 | both no  15

    Po = (20 + 15) / 50 = 0.70
    Pe = (25/50)(30/50) + (25/50)(20/50) = 0.30 + 0.20 = 0.50
    κ  = (0.70 - 0.50) / (1 - 0.50) = 0.40
    """
    pairs = [("yes", "yes")] * 20 + [("yes", "no")] * 5 + [("no", "yes")] * 10 + [("no", "no")] * 15
    result = cohens_kappa(pairs)
    assert result.observed == pytest.approx(0.70)
    assert result.expected == pytest.approx(0.50)
    assert result.kappa == pytest.approx(0.40)
    assert result.method == "cohen"


def test_cohens_kappa_perfect_agreement_two_categories_is_one():
    assert cohens_kappa([("a", "a"), ("b", "b")]).kappa == pytest.approx(1.0)


def test_cohens_kappa_total_disagreement_is_minus_one():
    """Po = 0, Pe = 0.5 → κ = (0 − 0.5) / 0.5 = −1."""
    assert cohens_kappa([("a", "b"), ("b", "a")]).kappa == pytest.approx(-1.0)


def test_cohens_kappa_is_undefined_when_everyone_used_one_category():
    """Pe == 1 → κ is 0/0. Reported as None rather than a fabricated 1.0."""
    result = cohens_kappa([("a", "a"), ("a", "a")])
    assert result.kappa is None
    assert result.observed == 1.0


def test_empty_input_yields_no_kappa():
    assert cohens_kappa([]).kappa is None
    assert fleiss_kappa([]).kappa is None


# --- Fleiss' kappa (K > 2) --------------------------------------------------


def test_fleiss_kappa_hand_computed_fixture():
    """3 raters, 4 items, 2 categories:

        [A,A,A] → P_i = (3² − 3) / (3·2) = 1
        [A,A,B] → (2² + 1² − 3) / 6 = 2/6
        [B,B,B] → 1
        [A,B,B] → 2/6

    Po = (1 + 1/3 + 1 + 1/3) / 4 = 2/3
    marginals: A = 6/12, B = 6/12  →  Pe = 0.5² + 0.5² = 0.5
    κ  = (2/3 − 1/2) / (1 − 1/2) = 1/3
    """
    result = fleiss_kappa([["A", "A", "A"], ["A", "A", "B"], ["B", "B", "B"], ["A", "B", "B"]])
    assert result.observed == pytest.approx(2 / 3)
    assert result.expected == pytest.approx(0.5)
    assert result.kappa == pytest.approx(1 / 3)
    assert result.method == "fleiss"
    assert result.n_items == 4


def test_fleiss_drops_items_with_a_non_modal_rater_count():
    """Fleiss assumes a constant rater count; mixing them biases Pe."""
    result = fleiss_kappa(
        [["A", "A", "A"], ["A", "A", "B"], ["B", "B", "B"], ["A", "B", "B"], ["A", "B"]]
    )
    assert result.n_items == 4  # the 2-rater item was dropped


def test_kappa_dispatches_on_rater_count():
    assert kappa([["a", "b"], ["a", "a"]]).method == "cohen"
    assert kappa([["a", "b", "a"], ["a", "a", "b"]]).method == "fleiss"
    assert kappa([[]]).method == "none"


# --- vote entropy -----------------------------------------------------------


def test_entropy_is_zero_when_unanimous():
    assert vote_entropy(["a", "a", "a"]) == 0.0


def test_entropy_is_one_on_an_even_split():
    assert vote_entropy(["a", "b"]) == pytest.approx(1.0)
    assert vote_entropy(["a", "a", "b", "b"]) == pytest.approx(1.0)


def test_entropy_of_a_three_to_one_split():
    """H = −(0.75·ln0.75 + 0.25·ln0.25) = 0.562335 nats; ÷ ln2 = 0.811278."""
    expected = -(0.75 * math.log(0.75) + 0.25 * math.log(0.25)) / math.log(2)
    assert vote_entropy(["a", "a", "a", "b"]) == pytest.approx(expected)
    assert vote_entropy(["a", "a", "a", "b"]) == pytest.approx(0.811278, abs=1e-6)


# --- consensus rate (§6.4) --------------------------------------------------


def test_exact_consensus_is_the_plurality_share():
    result = key_consensus("category", ["cat", "cat", "dog"], MatchRule(min_consensus=0.67))
    assert result.winner == "cat"
    assert result.support == 2
    assert result.rate == pytest.approx(2 / 3)
    # 2/3 = 0.6667 clears a 0.67 policy: thresholds are compared to two decimals
    # so §6.4's own "0.67 means 2-of-3" example is satisfiable (CONSENSUS_EPSILON).
    assert result.agreed


def test_a_stricter_policy_fails_the_same_votes():
    result = key_consensus("category", ["cat", "cat", "dog"], MatchRule(min_consensus=0.75))
    assert not result.agreed


def test_within_tolerance_counts_near_misses_as_consensus():
    """Likert ±1: votes 4,5,5 all agree with the candidate 4."""
    rule = MatchRule(match="within", tolerance=1, min_consensus=0.67)
    result = key_consensus("fluency", [4, 5, 5], rule)
    assert result.support == 3
    assert result.rate == pytest.approx(1.0)
    assert result.agreed


def test_within_tolerance_still_fails_a_genuine_spread():
    rule = MatchRule(match="within", tolerance=1, min_consensus=0.67)
    result = key_consensus("fluency", [1, 3, 5], rule)
    assert result.support == 1
    assert not result.agreed


def test_jaccard_consensus_on_multi_select():
    rule = MatchRule(match="jaccard", threshold=0.5, min_consensus=0.67)
    result = key_consensus("quality_flags", [["a", "b"], ["a", "b", "c"], ["x"]], rule)
    assert result.support == 2  # the two overlapping answers
    assert result.agreed


def test_no_votes_is_not_consensus():
    result = key_consensus("k", [], MatchRule())
    assert not result.agreed and result.votes == 0
