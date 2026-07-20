"""Slot pre-generation with variant balance (§2.7, §12 invariant 1) and the
slot/unit lifecycle primitives shared by assignment and quality."""

from app.services.slots.generation import (
    plan_slot_variants,
    variant_values,
    verify_balance,
)
from app.services.slots.lifecycle import (
    recompute_unit_status,
    reopen_slot,
    void_labels,
)

__all__ = [
    "plan_slot_variants",
    "recompute_unit_status",
    "reopen_slot",
    "variant_values",
    "verify_balance",
    "void_labels",
]
