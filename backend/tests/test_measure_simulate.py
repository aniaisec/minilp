"""Simulated raters (docs/MEASUREMENT.md) — the answer model, without a server.

The simulator is only worth running if a persona's accuracy means what it says,
including on positional templates where "correct" is a *side* that depends on the
slot's variant. These pin that against the server's own canonicalizer.
"""

import random

import pytest

from app.measure.simulate import (
    PERSONAS,
    Persona,
    SimulationError,
    answer_options,
    choose_answer,
    parse_mix,
)
from app.services.quality.canonical import canonicalize_positional
from app.services.templates.seed import IMAGE_CLASSIFICATION, SIDE_BY_SIDE, TEXT_SENTIMENT

CHOICE = SIDE_BY_SIDE["inputs"][0]
CATEGORY = IMAGE_CLASSIFICATION["inputs"][0]
ORACLE = Persona("oracle", 1.0, (1, 1))
CONTRARIAN = Persona("contrarian", 0.0, (1, 1))


def test_parse_mix_expands_counts_in_order() -> None:
    assert parse_mix("typical:2,spammer:1,expert") == ["typical", "typical", "spammer", "expert"]
    with pytest.raises(SimulationError, match="unknown persona"):
        parse_mix("wizard:1")


def test_answer_options_cover_discrete_inputs() -> None:
    assert answer_options(CATEGORY) == ["cat", "dog", "bird"]
    assert answer_options(TEXT_SENTIMENT["inputs"][1]) == [1, 2, 3, 4, 5]
    assert answer_options({"type": "boolean"}) == [True, False]
    assert answer_options({"type": "free_text"}) == []


@pytest.mark.parametrize(
    ("variant", "truth", "side"),
    [("AB", "A", "Left"), ("BA", "A", "Right"), ("BA", "B", "Left"), ("AB", "Tie", "Tie")],
)
def test_an_accurate_rater_clicks_the_side_the_true_item_is_on(variant, truth, side) -> None:
    rng = random.Random(0)
    answer = choose_answer(ORACLE, CHOICE, truth, variant, rng)
    assert answer == side
    # ...and the server maps that click back to the truth.
    assert canonicalize_positional(answer, variant) == truth


def test_a_zero_accuracy_rater_is_never_right() -> None:
    rng = random.Random(1)
    for _ in range(200):
        assert choose_answer(CONTRARIAN, CATEGORY, "cat", None, rng) != "cat"
        side = choose_answer(CONTRARIAN, CHOICE, "A", "BA", rng)
        assert canonicalize_positional(side, "BA") != "A"


def test_accuracy_is_honoured_in_aggregate() -> None:
    rng = random.Random(2)
    typical = PERSONAS["typical"]
    hits = sum(choose_answer(typical, CATEGORY, "dog", None, rng) == "dog" for _ in range(4000))
    assert hits / 4000 == pytest.approx(typical.accuracy, abs=0.02)


def test_spammer_ignores_truth_and_biased_rater_favours_the_first_option() -> None:
    rng = random.Random(3)
    seen = {choose_answer(PERSONAS["spammer"], CATEGORY, "cat", None, rng) for _ in range(200)}
    assert seen == {"cat", "dog", "bird"}
    always_left = Persona("left", 0.5, (1, 1), first_option_rate=1.0)
    assert {choose_answer(always_left, CHOICE, "A", "BA", rng) for _ in range(50)} == {"Left"}


def test_unknown_truth_answers_at_random_and_free_text_is_refused() -> None:
    rng = random.Random(4)
    assert choose_answer(ORACLE, CATEGORY, None, None, rng) in {"cat", "dog", "bird"}
    with pytest.raises(SimulationError, match="no discrete options"):
        choose_answer(ORACLE, {"id": "notes", "type": "free_text"}, "x", None, rng)
