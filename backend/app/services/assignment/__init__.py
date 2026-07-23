"""Assignment engine (M2, §6.4).

The engine hands open slots to annotators — human or judge worker, uniformly —
under four invariants:

1. **No double-assignment.** Slot selection uses ``SELECT … FOR UPDATE SKIP
   LOCKED`` so concurrent workers never lease the same slot (§4, §12).
2. **Annotator-unit exclusion.** An annotator never labels the same *unit*
   twice, in any variant (§2.7).
3. **Balance survives failures.** Skipped / expired / voided slots return to the
   pool retaining their variant designation, so a unit reaches exactly K/n per
   variant value at completion (§2.7).
4. **Priority within balance.** Open slots are ordered ``priority DESC,
   created_at ASC``; golds inject independently of priority at ``gold_ratio``
   (§6.4).
"""

from app.services.assignment.engine import (
    AssignmentError,
    available_work,
    check_eligibility,
    lease_expiry,
    next_task,
    should_serve_gold,
    skip_task,
    submit_label,
    sweep_expired_leases,
    void_unit,
)

__all__ = [
    "AssignmentError",
    "available_work",
    "check_eligibility",
    "lease_expiry",
    "next_task",
    "should_serve_gold",
    "skip_task",
    "submit_label",
    "sweep_expired_leases",
    "void_unit",
]
