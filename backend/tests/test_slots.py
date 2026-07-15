"""Slot pre-generation variant balance (§2.7, §12 invariant 1). Pure — no DB."""

import random

import pytest

from app.services.slots.generation import (
    divisibility_ok,
    plan_slot_variants,
    verify_balance,
)

VARIANT_TEMPLATE = {
    "name": "sbs",
    "inputs": [{"id": "c", "type": "choice_buttons", "label": "x", "options": ["L", "R"]}],
    "variants": {"dimension": "panel_order", "values": ["AB", "BA"], "balance": "strict"},
}

PLAIN_TEMPLATE = {
    "name": "plain",
    "inputs": [{"id": "c", "type": "radio", "label": "x", "options": ["a", "b"]}],
    "variants": None,
}


def test_variant_free_gets_k_null_slots() -> None:
    plan = plan_slot_variants(PLAIN_TEMPLATE, 3)
    assert plan == [None, None, None]
    assert verify_balance(plan, PLAIN_TEMPLATE)


def test_exact_balance_k_over_n() -> None:
    plan = plan_slot_variants(VARIANT_TEMPLATE, 4, rng=random.Random(0))
    counts = {"AB": 0, "BA": 0}
    for v in plan:
        counts[v["panel_order"]] += 1
    assert counts == {"AB": 2, "BA": 2}
    assert verify_balance(plan, VARIANT_TEMPLATE)


def test_non_divisible_k_raises() -> None:
    with pytest.raises(ValueError):
        plan_slot_variants(VARIANT_TEMPLATE, 3)


def test_divisibility_helper() -> None:
    assert divisibility_ok(VARIANT_TEMPLATE, 4)
    assert not divisibility_ok(VARIANT_TEMPLATE, 5)
    assert divisibility_ok(PLAIN_TEMPLATE, 1)


def test_balance_holds_for_many_k() -> None:
    rng = random.Random(42)
    for k in (2, 4, 6, 8, 10):
        plan = plan_slot_variants(VARIANT_TEMPLATE, k, rng=rng)
        assert len(plan) == k
        assert verify_balance(plan, VARIANT_TEMPLATE)
