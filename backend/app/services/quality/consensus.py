"""Consensus evaluation and dynamic overlap growth (§6.4).

When a unit's K labels are in, each input key is checked against its declared
consensus requirement. If any key falls short the project's ``on_disagreement``
policy decides what happens:

- ``escalate``          — flag the unit for human review immediately (M8 consumes it).
- ``grow_then_escalate`` — open another **balanced** round of slots (one per variant
  value, so the K/n invariant still holds at completion), up to
  ``max_labels_per_unit``; escalate only once growth is exhausted.

Consensus rate for a key is the share of votes agreeing with the best candidate
answer under that key's match rule. For ``exact`` this is the plurality share.
For ``within``/``jaccard`` — which are *not* transitive — every distinct vote is
tried as the candidate and the best support wins, which is the honest reading of
"how many raters agree with each other" for a tolerance-based rule.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Label, Project, Slot, Template, Unit
from app.services.quality.agreement import vote_entropy
from app.services.quality.matching import MatchRule, _hashable, rule_for, values_match
from app.services.slots.generation import plan_slot_variants, variant_values

ON_DISAGREEMENT_POLICIES = ("escalate", "grow_then_escalate")
DEFAULT_POLICY = "grow_then_escalate"

# Thresholds are written by humans as rounded fractions — §6.4's own example is
# ``min_consensus: 0.67`` for a 2-of-3 majority. Compared strictly, 2/3 = 0.6667
# fails 0.67 and that policy is unsatisfiable at K=3, which is a trap rather than
# a feature. Consensus is therefore compared to two decimal places.
CONSENSUS_EPSILON = 0.005


@dataclass
class KeyConsensus:
    key: str
    winner: Any
    support: int
    votes: int
    rate: float
    required: float
    agreed: bool
    entropy: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "support": self.support,
            "votes": self.votes,
            "rate": round(self.rate, 4),
            "required": self.required,
            "agreed": self.agreed,
            "entropy": round(self.entropy, 4),
        }


@dataclass
class ConsensusResult:
    unit_id: int
    complete: bool  # has the unit collected its target label count?
    agreed: bool  # every key met its consensus requirement
    keys: list[KeyConsensus] = field(default_factory=list)
    action: str = "none"  # none | agreed | grown | escalated | pending
    slots_added: int = 0

    @property
    def failed_keys(self) -> list[str]:
        return [k.key for k in self.keys if not k.agreed]

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "complete": self.complete,
            "agreed": self.agreed,
            "action": self.action,
            "slots_added": self.slots_added,
            "failed_keys": self.failed_keys,
            "keys": {k.key: k.as_dict() for k in self.keys},
            "evaluated_at": datetime.now(UTC).isoformat(),
        }


def _utcnow() -> datetime:
    return datetime.now(UTC)


def key_consensus(key: str, votes: list[Any], rule: MatchRule) -> KeyConsensus:
    """Best-supported answer for one key and whether it clears ``min_consensus``."""
    n = len(votes)
    if n == 0:
        return KeyConsensus(key, None, 0, 0, 0.0, rule.min_consensus, False, 0.0)

    if rule.match == "exact":
        winner, support = Counter(_hashable(v) for v in votes).most_common(1)[0]
    else:
        # Non-transitive rules: try each distinct vote as the candidate.
        best: tuple[Any, int] = (None, -1)
        seen: list[Any] = []
        for candidate in votes:
            if any(_hashable(candidate) == _hashable(s) for s in seen):
                continue
            seen.append(candidate)
            support = sum(1 for v in votes if values_match(v, candidate, rule))
            if support > best[1]:
                best = (candidate, support)
        winner, support = best

    rate = support / n
    return KeyConsensus(
        key=key,
        winner=winner,
        support=support,
        votes=n,
        rate=rate,
        required=rule.min_consensus,
        agreed=rate + CONSENSUS_EPSILON >= rule.min_consensus,
        entropy=vote_entropy(votes),
    )


def evaluate_unit(db: Session, unit: Unit, project: Project) -> ConsensusResult:
    """Per-key consensus over a unit's valid labels. Read-only."""
    labels = list(
        db.scalars(select(Label).where(Label.unit_id == unit.id, Label.is_valid.is_(True)))
    )
    target = project.labels_per_unit
    open_or_leased = db.scalar(
        select(Slot).where(Slot.unit_id == unit.id, Slot.status.in_(("open", "leased"))).limit(1)
    )
    complete = len(labels) >= target and open_or_leased is None

    votes_by_key: dict[str, list[Any]] = {}
    for label in labels:
        for key, value in (label.value or {}).items():
            votes_by_key.setdefault(key, []).append(value)

    keys = [
        key_consensus(key, votes, rule_for(project.agreement, key))
        for key, votes in sorted(votes_by_key.items())
    ]
    return ConsensusResult(
        unit_id=unit.id,
        complete=complete,
        agreed=all(k.agreed for k in keys) if keys else False,
        keys=keys,
        action="pending" if not complete else ("agreed" if all(k.agreed for k in keys) else "none"),
    )


def _policy(project: Project) -> str:
    config = project.config or {}
    policy = (config.get("quality") or {}).get("on_disagreement") or config.get("on_disagreement")
    return policy if policy in ON_DISAGREEMENT_POLICIES else DEFAULT_POLICY


def _slot_count(db: Session, unit_id: int) -> int:
    """Slots that still count toward the unit's overlap (voided ones don't)."""
    return len(
        list(db.scalars(select(Slot.id).where(Slot.unit_id == unit_id, Slot.status != "voided")))
    )


def grow_overlap(db: Session, unit: Unit, project: Project) -> int:
    """Open one more balanced round of slots for a disagreeing unit (§6.4).

    A "round" is exactly n slots — one per variant value — so growth can never
    break the K/n invariant; variant-free templates grow by 1. Returns the number
    of slots added (0 when ``max_labels_per_unit`` leaves no room).
    """
    template = db.get(Template, project.template_id)
    if template is None:
        return 0
    schema = template.schema
    values = variant_values(schema)
    step = len(values) if values else 1

    current = _slot_count(db, unit.id)
    if current + step > project.max_labels_per_unit:
        return 0

    for variant in plan_slot_variants(schema, step):
        db.add(Slot(unit_id=unit.id, variant=variant, status="open"))
    db.flush()
    return step


def escalate(db: Session, unit: Unit, result: ConsensusResult, reason: str) -> None:
    """Flag a unit for human review (§7.2); the queue itself lands in M8."""
    unit.escalated_at = _utcnow()
    unit.quality = {**result.as_dict(), "escalation_reason": reason}
    db.flush()


def apply_consensus_policy(db: Session, unit: Unit, project: Project) -> ConsensusResult:
    """Evaluate a unit and act on the project's disagreement policy.

    Called after each label lands. A unit still collecting labels is left alone;
    a unit whose K labels agree is recorded as agreed (finalization is M8's job);
    a disagreeing unit grows or escalates.
    """
    result = evaluate_unit(db, unit, project)
    if not result.complete:
        unit.quality = result.as_dict()
        db.flush()
        return result

    if result.agreed:
        result.action = "agreed"
        unit.quality = result.as_dict()
        db.flush()
        return result

    if _policy(project) == "grow_then_escalate":
        added = grow_overlap(db, unit, project)
        if added:
            result.action = "grown"
            result.slots_added = added
            unit.quality = result.as_dict()
            # More labels are coming; the unit is back in the pool.
            unit.status = "in_progress"
            db.flush()
            return result
        # Set the action *before* escalating: ``escalate`` snapshots the result
        # into ``unit.quality``, and a snapshot claiming action="none" on an
        # escalated unit would mislead every reader of the review queue.
        result.action = "escalated"
        escalate(db, unit, result, reason="max_labels_per_unit reached without consensus")
        return result

    result.action = "escalated"
    escalate(db, unit, result, reason="on_disagreement=escalate")
    return result
