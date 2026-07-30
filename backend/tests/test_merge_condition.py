"""The pipeline condition evaluator (§7.2) — pure, no DB.

A routing condition arrives from a project's stored ``pipeline``: from the
network, from a PATCH, later from an imported marketplace bundle (M10). These
tests are therefore as much about what the grammar *refuses* as about what it
computes — the whole point of hand-parsing instead of calling ``eval``.
"""

import pytest

from app.services.merge.condition import ConditionError, check_condition, evaluate_condition

ENV = {"consensus": 0.92, "entropy": 0.2, "votes": 3.0, "judge_votes": 2.0, "human_votes": 1.0}


# --- the shipped default -----------------------------------------------------


def test_the_shipped_default_condition_reads_as_written():
    """§7.2's own example, evaluated both ways round."""
    condition = "consensus >= 0.9 && entropy <= 0.3"
    assert evaluate_condition(condition, ENV) is True
    assert evaluate_condition(condition, {**ENV, "consensus": 0.5}) is False
    assert evaluate_condition(condition, {**ENV, "entropy": 0.8}) is False


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("consensus > 0.9", True),
        ("consensus < 0.9", False),
        ("votes == 3", True),
        ("votes != 3", False),
        ("entropy <= 0.2", True),
        ("judge_votes >= 2 || consensus < 0.1", True),
        ("judge_votes >= 9 || consensus < 0.1", False),
        ("!(consensus < 0.5)", True),
        ("not (consensus > 0.5)", False),
        ("consensus >= 0.9 and human_votes >= 1", True),
        ("(consensus >= 0.9 && entropy <= 0.3) || votes >= 10", True),
        ("true", True),
        ("false", False),
    ],
)
def test_operators(condition, expected):
    assert evaluate_condition(condition, ENV) is expected


def test_an_absent_or_blank_condition_means_always():
    """A stage with no ``if`` runs; §7.2's ensemble stage has none."""
    assert evaluate_condition(None, ENV) is True
    assert evaluate_condition("   ", ENV) is True


# --- what it refuses ---------------------------------------------------------


def test_an_unknown_variable_is_an_error_not_a_silent_false():
    """A rule that quietly never fires is the worst failure mode for routing:
    units pile up in review with nothing to point at."""
    with pytest.raises(ConditionError) as e:
        evaluate_condition("consensuss >= 0.9", ENV)
    assert "unknown variable" in str(e.value)
    assert "consensus" in str(e.value)  # the message lists what *is* available


@pytest.mark.parametrize(
    "condition",
    [
        "__import__('os').system('rm -rf /')",
        "open('/etc/passwd').read()",
        "consensus.__class__",
        "[c for c in range(10)]",
        "lambda: 1",
        "consensus = 0.9",
        "consensus >= ",
        "(consensus >= 0.9",
        "consensus >= 0.9 &&",
        "@@@",
    ],
)
def test_hostile_and_malformed_conditions_raise(condition):
    with pytest.raises(ConditionError):
        evaluate_condition(condition, ENV)


def test_check_condition_validates_names_without_a_unit():
    """Save-time validation: the same parse, against the *names* a stage may use."""
    check_condition("consensus >= 0.9 && entropy <= 0.3", set(ENV))
    with pytest.raises(ConditionError):
        check_condition("nonsense >= 1", set(ENV))


def test_booleans_and_numbers_compare_interchangeably():
    """``is_gold == true`` and ``is_gold == 1`` must not mean different things."""
    env = {"is_gold": 1.0}
    assert evaluate_condition("is_gold == true", env) is True
    assert evaluate_condition("is_gold == 1", env) is True
    assert evaluate_condition("is_gold == false", {"is_gold": 0.0}) is True
