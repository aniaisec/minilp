"""Slot pre-generation with variant balance (§2.7).

Invariant (§12.1): for a variant-bearing template with n values and overlap K, each
unit gets exactly K/n slots per variant value — at creation and at completion.
Templates without variants get K plain slots (variant = null).

``plan_slot_variants`` is pure (returns the ordered list of variant dicts to
persist); the DB write happens in the ingest/project service so this stays testable
without a database.
"""

import random
from typing import Any


def variant_values(template_schema: dict[str, Any]) -> list[str] | None:
    """The declared variant values, or None for a variant-free template."""
    variants = template_schema.get("variants")
    if not variants:
        return None
    return list(variants.get("values", []))


def n_variant_values(template_schema: dict[str, Any]) -> int:
    values = variant_values(template_schema)
    return len(values) if values else 1


def divisibility_ok(template_schema: dict[str, Any], labels_per_unit: int) -> bool:
    """§2.7 / §4 CHECK: K must be divisible by the number of variant values."""
    return labels_per_unit % n_variant_values(template_schema) == 0


def plan_slot_variants(
    template_schema: dict[str, Any],
    labels_per_unit: int,
    *,
    shuffle: bool = True,
    rng: random.Random | None = None,
) -> list[dict[str, Any] | None]:
    """Return the ordered list of ``variant`` values (one per slot) for one unit.

    Length == ``labels_per_unit``. For variant templates, values are balanced
    exactly K/n each; order is shuffled (§2.7) so sessions have no predictable
    variant rhythm. For variant-free templates, returns ``[None] * K``.
    """
    if labels_per_unit < 1:
        raise ValueError("labels_per_unit must be >= 1")

    values = variant_values(template_schema)
    if not values:
        return [None] * labels_per_unit

    n = len(values)
    if labels_per_unit % n != 0:
        raise ValueError(
            f"labels_per_unit={labels_per_unit} not divisible by {n} variant values {values}"
        )

    dimension = template_schema["variants"]["dimension"]
    per_value = labels_per_unit // n
    plan: list[dict[str, Any] | None] = [{dimension: v} for v in values for _ in range(per_value)]
    if shuffle:
        (rng or random).shuffle(plan)
    return plan


def verify_balance(
    variants: list[dict[str, Any] | None],
    template_schema: dict[str, Any],
) -> bool:
    """Assert the K/n-per-value invariant holds for a unit's slot variants."""
    values = variant_values(template_schema)
    if not values:
        return all(v is None for v in variants)
    dimension = template_schema["variants"]["dimension"]
    counts = {v: 0 for v in values}
    for var in variants:
        if not var or dimension not in var:
            return False
        val = var[dimension]
        if val not in counts:
            return False
        counts[val] += 1
    return len(set(counts.values())) == 1
