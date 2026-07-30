"""The routing pipeline (§7.2) — declarative stages over a completed unit.

A project's ``pipeline`` is an ordered list of stage objects. The one that ships::

    [ { "stage": "ensemble",      "merge": "calibration_weighted" },
      { "stage": "auto_finalize", "if": "consensus >= 0.9 && entropy <= 0.3" },
      { "stage": "human_review",  "else": true } ]

Read it top to bottom: merge the votes, finalize if the merge is decisive,
otherwise send it to a human. Every stage is a named function in a registry, so
"arbitrary stage types are the extension point" (§7.2) is literally true — a
deployment adds ``expert_review`` by calling ``register_stage`` and naming it in
a project's pipeline, with no fork of this module. See ``docs/extending.md``.

Three properties worth defending:

**Terminal stages stop the run.** ``auto_finalize`` and ``human_review`` end the
pipeline when they act. That is what makes ``"else": true`` on the last stage
honest rather than decorative — it is only reached because nothing above it
decided.

**Running twice is safe.** Routing runs after every label lands, and can be
re-run over a whole project from the admin surface. A unit that is already
finalized by a *human* is left strictly alone: a reviewer's decision must not be
undone by a later automatic pass. A unit auto-finalized earlier is re-merged and
may move, because that is just a better answer from more votes.

**Nothing here writes labels or touches slots.** Routing reads labels, writes at
most one ``final_labels`` row, and sets ``units.escalated_at``. Slot balance
(§2.7) is unreachable from here, which is deliberate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import Project, Unit
from app.services.merge.condition import ConditionError, check_condition, evaluate_condition
from app.services.merge.finalize import (
    check_project_completed,
    final_label_for,
    finalize_unit,
)
from app.services.merge.merge import MERGE_METHODS, MergeResult, merge_unit
from app.services.webhooks import Sender

__all__ = [
    "DEFAULT_PIPELINE",
    "CONDITION_VARIABLES",
    "PipelineError",
    "RoutingResult",
    "StageContext",
    "effective_pipeline",
    "register_stage",
    "registered_stages",
    "route_unit",
    "validate_pipeline",
]

# §7.2's shipped default, minus the illustrative judge names: with no ``judges``
# key the ensemble merges every valid label, so this same default is correct for
# a judge-only project, a human-only project, and a mixed one.
DEFAULT_PIPELINE: list[dict[str, Any]] = [
    {"stage": "ensemble", "merge": "calibration_weighted"},
    {"stage": "auto_finalize", "if": "consensus >= 0.9 && entropy <= 0.3"},
    {"stage": "human_review", "else": True},
]

# Names a stage condition may reference. Kept in one place so validation at save
# time and evaluation at run time can never drift apart.
CONDITION_VARIABLES = {
    "consensus",
    "confidence",
    "entropy",
    "votes",
    "judge_votes",
    "human_votes",
    "priority",
    "is_gold",
    "escalated",
}

HUMAN_METHODS = ("human_approved", "human_override", "expert")


class PipelineError(ValueError):
    """An invalid pipeline document."""


@dataclass
class StageContext:
    """Everything a stage may read, and the one slot it may write."""

    db: Session
    unit: Unit
    project: Project
    spec: dict[str, Any]
    proposal: MergeResult | None = None
    sender: Sender | None = None
    sleep: Callable[[float], None] | None = None
    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    def metrics(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "consensus": 0.0,
            "confidence": 0.0,
            "entropy": 1.0,
            "votes": 0.0,
            "judge_votes": 0.0,
            "human_votes": 0.0,
        }
        if self.proposal is not None:
            base.update(self.proposal.metrics())
        base["priority"] = float(self.unit.priority or 0)
        base["is_gold"] = 1.0 if self.unit.is_gold else 0.0
        base["escalated"] = 1.0 if self.unit.escalated_at else 0.0
        return base


@dataclass
class StageOutcome:
    """What a stage did: a note for the trace, and whether the run stops."""

    action: str
    stop: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingResult:
    unit_id: int
    decision: str = "none"  # none | auto_finalized | escalated | skipped | human_decided
    stages: list[dict[str, Any]] = field(default_factory=list)
    proposal: MergeResult | None = None
    final_label_id: int | None = None
    webhooks_fired: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "decision": self.decision,
            "stages": self.stages,
            "final_label_id": self.final_label_id,
            "proposal": self.proposal.as_dict() if self.proposal else None,
            "webhooks_fired": self.webhooks_fired,
        }


# --- the stage registry (§7.2 "arbitrary stage types are the extension point") -

StageFn = Callable[[StageContext], StageOutcome]
_REGISTRY: dict[str, StageFn] = {}


def register_stage(name: str, fn: StageFn) -> None:
    """Add (or replace) a pipeline stage type. See ``docs/extending.md``."""
    _REGISTRY[name] = fn


def registered_stages() -> list[str]:
    return sorted(_REGISTRY)


def _gate(ctx: StageContext) -> bool:
    """Evaluate a stage's ``if`` (``else`` is a marker, not a second condition)."""
    condition = ctx.spec.get("if")
    if condition is None:
        return True
    return evaluate_condition(str(condition), ctx.metrics())


def stage_ensemble(ctx: StageContext) -> StageOutcome:
    """Merge the unit's votes into a proposal (§7.2 calibration-weighted merge)."""
    method = ctx.spec.get("merge") or "calibration_weighted"
    judges = ctx.spec.get("judges") or None
    kinds = ctx.spec.get("kinds") or None
    ctx.proposal = merge_unit(
        ctx.db,
        ctx.unit,
        ctx.project,
        method=method,
        judges=list(judges) if judges else None,
        kinds=tuple(kinds) if kinds else None,
    )
    if ctx.proposal is None:
        return StageOutcome("no_votes", detail={"merge": method, "judges": judges})
    return StageOutcome(
        "merged",
        detail={
            "merge": method,
            "judges": judges,
            "voters": ctx.proposal.voter_count,
            "consensus": round(ctx.proposal.confidence, 4),
            "entropy": round(ctx.proposal.entropy, 4),
        },
    )


def stage_auto_finalize(ctx: StageContext) -> StageOutcome:
    """Finalize when the merge clears the stage's threshold (§7.2)."""
    if ctx.proposal is None:
        return StageOutcome("skipped", detail={"reason": "no proposal to finalize"})
    if not _gate(ctx):
        return StageOutcome(
            "not_met",
            detail={"if": ctx.spec.get("if"), **ctx.proposal.metrics()},
        )
    final = finalize_unit(
        ctx.db,
        ctx.unit,
        value=ctx.proposal.value,
        method="auto_consensus",
        confidence=round(ctx.proposal.confidence, 6),
        provenance={
            "stage": "auto_finalize",
            "if": ctx.spec.get("if"),
            "decided_at": ctx.now.isoformat(),
            **ctx.proposal.provenance(),
        },
    )
    return StageOutcome("finalized", stop=True, detail={"final_label_id": final.id})


def stage_human_review(ctx: StageContext) -> StageOutcome:
    """Route the unit to the human review queue (§7.2 escalate on disagreement)."""
    if not _gate(ctx):
        return StageOutcome("not_met", detail={"if": ctx.spec.get("if")})
    reason = ctx.spec.get("reason") or "routed to human review by pipeline"
    ctx.unit.escalated_at = ctx.unit.escalated_at or ctx.now
    snapshot = dict(ctx.unit.quality or {})
    snapshot["escalation_reason"] = reason
    if ctx.proposal is not None:
        snapshot["proposal"] = ctx.proposal.as_dict()
    ctx.unit.quality = snapshot
    ctx.db.flush()
    return StageOutcome("escalated", stop=True, detail={"reason": reason})


register_stage("ensemble", stage_ensemble)
register_stage("auto_finalize", stage_auto_finalize)
register_stage("human_review", stage_human_review)


# --- validation + execution ---------------------------------------------------


def effective_pipeline(project: Project) -> list[dict[str, Any]]:
    """The project's pipeline, or the shipped default when it has none (§7.2)."""
    pipeline = project.pipeline
    if not pipeline:
        return [dict(stage) for stage in DEFAULT_PIPELINE]
    return [dict(stage) for stage in pipeline]


def validate_pipeline(pipeline: Any) -> list[dict[str, Any]]:
    """Check a pipeline document at save time. Raises ``PipelineError``.

    Validating here rather than at run time is the difference between a 422 on
    the project edit and a routing rule that silently never fires.
    """
    if pipeline is None:
        return []
    if not isinstance(pipeline, list):
        raise PipelineError("pipeline must be a list of stage objects")
    out: list[dict[str, Any]] = []
    for index, spec in enumerate(pipeline):
        where = f"pipeline[{index}]"
        if not isinstance(spec, dict):
            raise PipelineError(f"{where} must be an object")
        name = spec.get("stage")
        if not name:
            raise PipelineError(f"{where} is missing 'stage'")
        if name not in _REGISTRY:
            raise PipelineError(f"{where}: unknown stage '{name}' (known: {registered_stages()})")
        method = spec.get("merge")
        if method is not None and method not in MERGE_METHODS:
            raise PipelineError(f"{where}: unknown merge '{method}' (known: {list(MERGE_METHODS)})")
        judges = spec.get("judges")
        if judges is not None and (
            not isinstance(judges, list) or not all(isinstance(j, str) for j in judges)
        ):
            raise PipelineError(f"{where}: 'judges' must be a list of judge config names")
        condition = spec.get("if")
        if condition is not None:
            try:
                check_condition(str(condition), CONDITION_VARIABLES)
            except ConditionError as e:
                raise PipelineError(f"{where}: {e}") from e
        out.append(dict(spec))
    return out


def _is_human_decided(db: Session, unit: Unit) -> bool:
    final = final_label_for(db, unit.id)
    return final is not None and final.method in HUMAN_METHODS


def route_unit(
    db: Session,
    unit: Unit,
    project: Project,
    *,
    sender: Sender | None = None,
    sleep: Callable[[float], None] | None = None,
    now: datetime | None = None,
) -> RoutingResult:
    """Run the project's routing pipeline over one unit (§7.2).

    Safe to call after every label and safe to call again later; a unit a human
    has already decided is never re-decided automatically.
    """
    result = RoutingResult(unit_id=unit.id)
    if _is_human_decided(db, unit):
        result.decision = "skipped"
        result.stages.append({"stage": "-", "action": "human_decided", "detail": {}})
        return result

    ctx = StageContext(
        db=db,
        unit=unit,
        project=project,
        spec={},
        sender=sender,
        sleep=sleep,
        now=now or datetime.now(UTC),
    )
    for spec in effective_pipeline(project):
        name = spec.get("stage")
        fn = _REGISTRY.get(str(name))
        if fn is None:
            result.stages.append(
                {"stage": name, "action": "unknown_stage", "detail": {"skipped": True}}
            )
            continue
        ctx.spec = spec
        outcome = fn(ctx)
        result.stages.append({"stage": name, "action": outcome.action, "detail": outcome.detail})
        if outcome.action == "finalized":
            result.decision = "auto_finalized"
            result.final_label_id = outcome.detail.get("final_label_id")
        elif outcome.action == "escalated":
            result.decision = "escalated"
        if outcome.stop:
            break
    result.proposal = ctx.proposal

    if result.decision == "auto_finalized":
        result.webhooks_fired += check_project_completed(db, project, sender=sender, sleep=sleep)
    elif result.decision == "escalated":
        from app.services.merge.review import check_backlog  # circular at import time only

        result.webhooks_fired += check_backlog(db, project, sender=sender, sleep=sleep)
    return result
