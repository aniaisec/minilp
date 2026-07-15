"""Slot pre-generation with variant balance (§2.7, §12 invariant 1)."""

from app.services.slots.generation import (
    plan_slot_variants,
    variant_values,
    verify_balance,
)

__all__ = ["plan_slot_variants", "variant_values", "verify_balance"]
