"""Calibration-weighted merge (§7.2).

Given a unit's valid labels, produce **one proposed answer per input key**, a
confidence, and the full provenance §7.2 asks for: *who voted what, at which
weight, in which variant*.

The merge reuses the §6.4 match rules rather than inventing its own notion of
"the same answer": a likert key declared ``{"match": "within", "tolerance": 1}``
merges 3 and 4 into one candidate exactly as it counts them as agreeing, and a
``jaccard`` key merges overlapping tag sets. Consensus and merge therefore can
never disagree about what "agreeing" means — which matters, because the routing
pipeline reads both.

Three definitions, chosen once and applied everywhere downstream:

- **Winner (per key)** — the candidate with the greatest summed weight. Ties break
  toward the candidate with more raw votes, then deterministically by repr, so
  re-merging the same unit never flips the answer.
- **Consensus (per unit)** — the *minimum* per-key weight share. A unit is only as
  decided as its least-decided key; auto-finalizing a unit because two of its
  three keys were unanimous is how bad labels get into a training set.
- **Entropy (per unit)** — the *maximum* per-key vote entropy, by the same logic,
  and computed on unweighted votes (§6.3) so it measures rater disagreement
  rather than the weighting. Crucially it is computed over the *match-rule
  buckets*, not over distinct raw values: on a likert key declared
  ``{"match": "within", "tolerance": 1}``, votes of 4 and 5 are one answer, and
  an entropy that called them maximally divergent would send units the project
  has explicitly declared to be in agreement straight to human review.

Read-only: nothing here writes. ``finalize`` decides whether the proposal becomes
a ``final_label``; this module only says what the proposal *is*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotator, JudgeConfig, Label, Project, Slot, Template, Unit
from app.services.merge.weights import merge_weight
from app.services.quality.agreement import vote_entropy
from app.services.quality.matching import (
    MatchRule,
    _hashable,
    input_types,
    rule_for,
    values_match,
)

__all__ = ["Candidate", "KeyMerge", "MergeResult", "Vote", "merge_unit"]

DEFAULT_METHOD = "calibration_weighted"
MERGE_METHODS = ("calibration_weighted", "majority")


@dataclass
class Candidate:
    """One distinct answer for a key, and the weight behind it."""

    value: Any
    weight: float
    support: int

    def as_dict(self, total_weight: float) -> dict[str, Any]:
        return {
            "value": self.value,
            "weight": round(self.weight, 4),
            "support": self.support,
            "share": round(self.weight / total_weight, 4) if total_weight else 0.0,
        }


@dataclass
class KeyMerge:
    key: str
    winner: Any
    weight: float
    total_weight: float
    support: int
    votes: int
    entropy: float
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def share(self) -> float:
        return self.weight / self.total_weight if self.total_weight else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "weight": round(self.weight, 4),
            "total_weight": round(self.total_weight, 4),
            "share": round(self.share, 4),
            "support": self.support,
            "votes": self.votes,
            "entropy": round(self.entropy, 4),
            "candidates": [c.as_dict(self.total_weight) for c in self.candidates],
        }


@dataclass
class Vote:
    """One rater's contribution, as the review queue displays it."""

    label_id: int
    annotator_id: int
    kind: str
    name: str | None
    judge: str | None
    reputation: float
    weight: float
    variant: dict[str, Any] | None
    value: dict[str, Any]
    raw: dict[str, Any]
    confidence: float | None
    reasoning: str | None
    cost_usd: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "label_id": self.label_id,
            "annotator_id": self.annotator_id,
            "kind": self.kind,
            "name": self.name,
            "judge": self.judge,
            "reputation": round(self.reputation, 4),
            "weight": round(self.weight, 4),
            "variant": self.variant,
            "value": self.value,
            "raw": self.raw,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "cost_usd": self.cost_usd,
        }


@dataclass
class MergeResult:
    unit_id: int
    method: str
    value: dict[str, Any]
    confidence: float
    entropy: float
    keys: list[KeyMerge] = field(default_factory=list)
    votes: list[Vote] = field(default_factory=list)

    @property
    def voter_count(self) -> int:
        return len(self.votes)

    @property
    def judge_votes(self) -> int:
        return sum(1 for v in self.votes if v.kind == "model")

    @property
    def human_votes(self) -> int:
        return sum(1 for v in self.votes if v.kind == "human")

    def metrics(self) -> dict[str, float]:
        """The environment a stage ``if`` condition is evaluated against (§7.2)."""
        return {
            "consensus": round(self.confidence, 6),
            "confidence": round(self.confidence, 6),
            "entropy": round(self.entropy, 6),
            "votes": float(self.voter_count),
            "judge_votes": float(self.judge_votes),
            "human_votes": float(self.human_votes),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "method": self.method,
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "entropy": round(self.entropy, 4),
            "votes": [v.as_dict() for v in self.votes],
            "keys": {k.key: k.as_dict() for k in self.keys},
        }

    def provenance(self) -> dict[str, Any]:
        """What §7.2 requires a finalized label to carry: who voted what, weighted."""
        return {
            "merge": self.method,
            "confidence": round(self.confidence, 4),
            "entropy": round(self.entropy, 4),
            "keys": {k.key: k.as_dict() for k in self.keys},
            "votes": [v.as_dict() for v in self.votes],
        }


def _judge_names(db: Session, annotators: list[Annotator]) -> dict[int, str | None]:
    """``annotator_id -> judge config name`` for the model raters among them."""
    config_ids = {a.judge_config_id for a in annotators if a.judge_config_id is not None}
    if not config_ids:
        return {a.id: None for a in annotators}
    names = {
        c.id: c.name for c in db.scalars(select(JudgeConfig).where(JudgeConfig.id.in_(config_ids)))
    }
    return {a.id: names.get(a.judge_config_id) if a.judge_config_id else None for a in annotators}


def _collect_votes(db: Session, unit: Unit) -> list[Vote]:
    labels = list(
        db.scalars(
            select(Label)
            .where(Label.unit_id == unit.id, Label.is_valid.is_(True))
            .order_by(Label.submitted_at, Label.id)
        )
    )
    if not labels:
        return []
    annotators = {
        a.id: a
        for a in db.scalars(
            select(Annotator).where(Annotator.id.in_({label.annotator_id for label in labels}))
        )
    }
    judges = _judge_names(db, list(annotators.values()))
    slots = {
        s.id: s
        for s in db.scalars(select(Slot).where(Slot.id.in_({label.slot_id for label in labels})))
    }

    votes: list[Vote] = []
    for label in labels:
        annotator = annotators.get(label.annotator_id)
        slot = slots.get(label.slot_id)
        votes.append(
            Vote(
                label_id=label.id,
                annotator_id=label.annotator_id,
                kind=annotator.kind if annotator else "human",
                name=annotator.display_name if annotator else None,
                judge=judges.get(label.annotator_id),
                reputation=float(annotator.reputation_score or 0.0) if annotator else 0.0,
                weight=merge_weight(annotator),
                variant=slot.variant if slot else None,
                value=label.value or {},
                raw=label.raw or {},
                confidence=label.confidence,
                reasoning=label.reasoning,
                cost_usd=label.cost_usd,
            )
        )
    return votes


def _merge_key(
    key: str,
    entries: list[tuple[Any, float]],
    rule: MatchRule,
    *,
    weighted: bool,
) -> KeyMerge:
    """Bucket one key's ``(value, weight)`` votes under its match rule and pick a winner.

    Candidates are built greedily in vote order: each vote joins the first
    existing candidate it *matches* under the rule, or opens a new one. For
    ``exact`` this is plain grouping; for the non-transitive rules (``within``,
    ``jaccard``) it is the same reading §6.4 already takes — "how many raters
    agree with each other" answered against a concrete representative.
    """
    buckets: list[tuple[Any, list[tuple[Any, float]]]] = []
    assignment: list[int] = []  # bucket index per vote, in vote order
    for value, weight in entries:
        for index, (representative, members) in enumerate(buckets):
            if values_match(value, representative, rule):
                members.append((value, weight))
                assignment.append(index)
                break
        else:
            assignment.append(len(buckets))
            buckets.append((value, [(value, weight)]))

    candidates = [
        Candidate(
            value=representative,
            weight=sum((w if weighted else 1.0) for _, w in members),
            support=len(members),
        )
        for representative, members in buckets
    ]
    # Deterministic ordering: weight, then raw support, then a stable text key —
    # so a re-merge of the same unit can never silently flip the answer.
    candidates.sort(key=lambda c: (-c.weight, -c.support, repr(_hashable(c.value))))
    total = sum(c.weight for c in candidates)
    top = candidates[0]
    return KeyMerge(
        key=key,
        winner=top.value,
        weight=top.weight,
        total_weight=total,
        support=top.support,
        votes=len(entries),
        # Entropy over bucket membership, so "the same answer under this key's
        # match rule" means the same thing here as it does to consensus (§6.4).
        entropy=vote_entropy(assignment),
        candidates=candidates,
    )


def merge_unit(
    db: Session,
    unit: Unit,
    project: Project,
    *,
    method: str = DEFAULT_METHOD,
    judges: list[str] | None = None,
    kinds: tuple[str, ...] | None = None,
) -> MergeResult | None:
    """Merge a unit's valid labels into one proposed answer, or ``None`` if it has none.

    ``judges`` restricts the ensemble to the named judge configs (§7.2's
    ``"judges": ["gpt-x-judge", ...]``); omitted, *every* valid label counts —
    which is what makes the shipped default pipeline correct for a project with
    no judges at all, where the ensemble is simply the humans. ``kinds`` narrows
    to ``("model",)`` or ``("human",)`` for the same reason at a coarser grain.
    """
    if method not in MERGE_METHODS:
        raise ValueError(f"unknown merge method '{method}' (known: {list(MERGE_METHODS)})")

    votes = _collect_votes(db, unit)
    if judges:
        wanted = set(judges)
        votes = [v for v in votes if v.judge in wanted]
    if kinds:
        votes = [v for v in votes if v.kind in kinds]
    if not votes:
        return None

    template = db.get(Template, project.template_id)
    types = input_types(template.schema if template else None)

    by_key: dict[str, list[tuple[Any, float]]] = {}
    for vote in votes:
        for key, value in (vote.value or {}).items():
            by_key.setdefault(key, []).append((value, vote.weight))

    weighted = method == DEFAULT_METHOD
    keys = [
        _merge_key(
            key,
            entries,
            rule_for(project.agreement, key, types.get(key)),
            weighted=weighted,
        )
        for key, entries in sorted(by_key.items())
    ]
    if not keys:
        return None

    return MergeResult(
        unit_id=unit.id,
        method=method,
        value={k.key: k.winner for k in keys},
        # A unit is only as decided as its least-decided key.
        confidence=min(k.share for k in keys),
        entropy=max(k.entropy for k in keys),
        keys=keys,
        votes=votes,
    )
